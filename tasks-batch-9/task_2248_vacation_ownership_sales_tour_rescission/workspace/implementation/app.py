"""Vacation Ownership Sales Tour & Rescission API.

Flask application factory and process entry point.  Storage is process memory
only (see store.py) and is never seeded: a fresh boot always starts empty.
"""

import errno
import os
import socket
import time

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import ALL_BLUEPRINTS

_METHOD_NOT_ALLOWED = 405


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _reset_dirty():
        g._dirty = []

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", 404, "resource not found")
        if status == _METHOD_NOT_ALLOWED:
            return error_response("ERR_INVALID_REQUEST", 400, "method not allowed")
        if status in (400, 415):
            return error_response("ERR_INVALID_REQUEST", 400, "malformed request")
        return error_response("ERR_INTERNAL", status, exc.description or "error")

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", 500, str(exc))

    @app.get("/healthz")
    def _healthz():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


_BIND_RETRY_SECONDS = 30.0
_BIND_RETRY_INTERVAL = 0.25


def _wait_for_free_port(port, deadline):
    """Block until nothing else holds ``port``, or the deadline passes."""
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("0.0.0.0", port))
            return
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE or time.monotonic() >= deadline:
                raise
        finally:
            probe.close()
        time.sleep(_BIND_RETRY_INTERVAL)


def _serve(port):
    """Bind and serve, retrying briefly while the port is still held.

    The process is restarted repeatedly on a fixed port, and the previous
    listener is reclaimed with SIGKILL; teardown is asynchronous, so a fresh
    boot can lose a race to EADDRINUSE.  Werkzeug turns that into an immediate
    ``sys.exit(1)``, which would leave the port unserved for a client that is
    already waiting, so drain the old socket first and retry the bind.
    """
    deadline = time.monotonic() + _BIND_RETRY_SECONDS
    while True:
        _wait_for_free_port(port, deadline)
        try:
            app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
            return
        except (OSError, SystemExit):
            if time.monotonic() >= deadline:
                raise
            time.sleep(_BIND_RETRY_INTERVAL)


if __name__ == "__main__":
    _serve(int(os.environ.get("PORT", "10000")))
