"""Kids Venue Booking API — Flask entry point.

Registers all blueprints and a central error handler that renders the standard
error envelope (PRD section 2.2). Storage is in-memory only (see db.py); nothing
is seeded at startup — every entity is created by tests via the declared endpoints.
"""

import os
import socket
import sys
import time

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes.bookings import bookings_bp
from routes.children import children_bp
from routes.config import config_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(children_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unmatched route — return the error envelope with a generic not-found.
        return error_response("ERR_BOOKING_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", 422, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected errors as a generic invalid-request rather than HTML.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % str(e))

    return app


app = create_app()


def _bind_socket(host, port, retries=80, delay=0.25):
    """Bind a listening socket with SO_REUSEADDR/SO_REUSEPORT, retrying briefly.

    Under per-test-server isolation the runner SIGKILLs the previous server and
    immediately respawns this one on the same port. The dying process's listening
    socket can linger for a moment, so a naive bind would hit "Address already in
    use", the process would exit, and the runner's restart poll would fail with a
    spurious "could not be restarted". SO_REUSEPORT plus a short retry loop lets the
    fresh process claim the port the instant it frees up.
    """
    last_err = None
    for _ in range(retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
        try:
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(True)
            return sock
        except OSError as e:
            last_err = e
            sock.close()
            time.sleep(delay)
    raise last_err if last_err else OSError("could not bind %s:%d" % (host, port))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    host = "0.0.0.0"
    listen_sock = _bind_socket(host, port)
    from werkzeug.serving import make_server

    server = make_server(host, port, app, threaded=True, fd=listen_sock.fileno())
    server.serve_forever()
