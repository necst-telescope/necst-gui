import logging
import os
import time
from pathlib import Path

import rclpy
from flask import Flask, redirect, render_template, request, url_for
from flask_socketio import SocketIO, join_room, leave_room
from neclib import EnvVarName

from .address import get_ip_address
from .client_manager import ClientManager, get_msg_type

logger = logging.getLogger(__name__)
ch = logging.StreamHandler()
fmt = logging.Formatter(
    "%(asctime)-s: [%(levelname)-s: %(filename)s#L%(lineno)s] %(message)s"
)
ch.setFormatter(fmt)
rootLogger = logging.getLogger()
rootLogger.setLevel(logging.INFO)
chs = [_ch for _ch in rootLogger.handlers if isinstance(_ch, logging.StreamHandler)]
[rootLogger.handlers.remove(_ch) for _ch in chs]
rootLogger.addHandler(ch)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


@app.route("/")
def index() -> str:
    return redirect(url_for("qlook"), code=302)


@app.route("/qlook")
def qlook() -> str:
    return render_template("index.html")


@app.route("/config")
def config() -> str:
    path = os.environ.get(EnvVarName.necst_root, None)
    try:
        return Path(path).read_text()
    except Exception:
        return ""


@socketio.on("connect", namespace="/qlook")
def connect(auth):
    logger.info(f"New Connection: {request.sid}")
    success = ClientManager(socketio).add_client(request.sid)
    return success


@socketio.on("disconnect", namespace="/qlook")
def disconnect():
    logger.info(f"Disconnected: {request.sid}")
    for _ in range(10):
        if ClientManager(socketio).remove_client(request.sid):
            break
        time.sleep(0.1)
    return True


@socketio.on("ros2-topic-list-request", namespace="/qlook")
def ros2_topic_list_request(json):
    logger.info(f"Got 'ros2-topic-list-request' from {request.sid}")
    topics = ClientManager(socketio).get_topic_names_and_types()
    topic_names = [t[0] for t in topics]
    socketio.emit("ros2-topic-list", {"topic_names": topic_names}, to=request.sid)


@socketio.on("ros2-topic-field-request", namespace="/qlook")
def ros2_topic_field_request(json):
    logger.info(f"Got 'ros2-topic-field-request' from {request.sid}")
    topic_name = json["topic_name"]
    msg_type = get_msg_type(topic_name)
    if msg_type is None:
        socketio.emit(
            "ros2-topic-field",
            {"error": f"Cannot find message type for {topic_name!r}"},
            to=request.sid,
        )
    socketio.emit(
        "ros2-topic-field",
        {"topic_name": topic_name, "fields": msg_type.get_fields_and_field_types()},
        to=request.sid,
    )


@socketio.on("ros2-subscribe-request", namespace="/qlook")
def ros2_subscribe_request(json):
    logger.info(f"Got 'ros2-subscribe-request' from {request.sid}")
    topic_name = json["topic_name"]
    success = ClientManager(socketio).add_subscription(request.sid, topic_name)
    if success:
        join_room(topic_name)
        logger.info(f"{request.sid} joined the room {topic_name!r}")
    socketio.emit("ros2-subscribe", {"success": success}, to=request.sid)


@socketio.on("ros2-unsubscribe-request", namespace="/qlook")
def ros2_unsubscribe_request(json):
    logger.info(f"Got 'ros2-unsubscribe-request' from {request.sid}")
    topic_name = json["topic_name"]
    success = ClientManager(socketio).remove_subscription(request.sid, topic_name)
    if success:
        leave_room(topic_name)
        logger.info(f"{request.sid} left the room {topic_name!r}")
    socketio.emit("ros2-unsubscribe", {"success": success}, to=request.sid)


def main():
    import argparse

    p = argparse.ArgumentParser(description="Graphical console for NECST system.")
    p.add_argument(
        "-p", "--port", type=int, default=8080, help="Port to use (default: 8080)"
    )
    p.add_argument(
        "-i",
        "--interface",
        type=str,
        help="Network interface or IP address to use "
        "(default: randomly chosen from available local IPv4 interfaces)",
    )
    args = p.parse_args()
    host = get_ip_address(args.interface)

    rclpy.init()
    logger.info("\033[1mTo detach this server, press Ctrl-P then Ctrl-Q.\033[0m")
    try:
        socketio.run(app, host=host, port=args.port)
    except Exception as e:
        logger.debug(e)
    finally:
        ClientManager().destroy_node()
        rclpy.try_shutdown()
