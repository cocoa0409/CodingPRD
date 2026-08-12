"""Equine Therapy & Therapeutic Riding API - entry point.

Storage is in-memory only and starts EMPTY on every boot: nothing is seeded,
preloaded or hardcoded, and every entity a client needs is created through a
declared endpoint.
"""

import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request                                    # noqa: E402

from core.envelope import error_response                            # noqa: E402
from core.errors import ApiError                                    # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        clockpolicy, crew, goals, horses, incidents, instructors, money,
        period_reports, releases, riders, sessions, volunteers,
    )
    for module in (clockpolicy, riders, releases, horses, volunteers, instructors,
                   sessions, crew, goals, money, incidents, period_reports):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "Method not allowed on this route.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error on %s %s", request.method, request.path)
        return error_response("ERR_VALIDATION", "Unprocessable request.", 400)

    return app


app = create_app()


def _bind(host, port, attempts=40, delay=0.25):
    """Bind our own listening socket, tolerating a still-closing predecessor.

    Under `--isolation per-test-server` the harness kill -9s the old server and
    immediately spawns the new one, so the port can still be held for a moment.
    Werkzeug converts a bind failure into SystemExit, which the harness reports
    as "API server could not be restarted" on an innocent test - wrapping
    app.run() in try/except OSError does NOT help.  Owning the socket ourselves
    is what makes the retry possible.
    """
    last = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(True)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
            time.sleep(delay)
    raise last


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    from werkzeug.serving import make_server
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
