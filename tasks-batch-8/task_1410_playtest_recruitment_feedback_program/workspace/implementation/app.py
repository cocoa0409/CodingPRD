"""Playtest Recruitment & Feedback Program API — Flask entry point.

The store is in-memory only and starts completely empty on every boot; the
harness restarts this process before every test (per-test-server isolation).
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error as error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, 400, "Malformed request")

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    import socket
    import time

    from werkzeug.serving import make_server

    _port = int(os.environ.get("PORT", "10000"))
    # Bind the listening socket ourselves with a retry loop: under the
    # per-test-server stability sweep many servers are killed and re-bound on
    # the same port in quick succession on a busy shared host, and a transient
    # EADDRINUSE at the exact bind instant must not be fatal (werkzeug's
    # app.run path sys.exits on it). The runner's restart-poll window is 15s;
    # retry briefly within it.
    _deadline = time.monotonic() + 12.0
    _sock = None
    while _sock is None:
        _candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            _candidate.bind(("0.0.0.0", _port))
            _candidate.listen(128)
            _sock = _candidate
        except OSError:
            _candidate.close()
            if time.monotonic() >= _deadline:
                raise
            time.sleep(0.2)

    _server = make_server("0.0.0.0", _port, app, threaded=True, fd=_sock.fileno())
    _server.serve_forever()
