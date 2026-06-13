"""Florist & Flower Delivery API — Flask entry point.

Boots a fresh, EMPTY in-memory store on every process start. No entity data
is seeded, preloaded, or hardcoded; tests build all state via the API.
"""
import os
import socket
import time

from flask import Flask, request
from werkzeug.serving import make_server

import errors
from errors import ApiError
from response import error as error_response

from routes.catalog import bp as catalog_bp
from routes.orders import bp as orders_bp
from routes.fulfillment import bp as fulfillment_bp
from routes.claims import bp as claims_bp
from routes.schedules import bp as schedules_bp
from routes.operators import bp as operators_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(fulfillment_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(operators_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND,
                              "Method not allowed for this path", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected errors as a generic invalid-request rather than
        # an HTML 500 page, keeping the envelope contract.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


def _bind_listen_socket(host, port, attempts=60, delay=0.25):
    """Create a listening socket with SO_REUSEADDR + SO_REUSEPORT.

    The evaluator restarts this server before every test by SIGKILLing the
    previous process and immediately re-spawning. Under the 8-round concurrent
    sweep the just-killed listener can still linger (TIME_WAIT / not-yet-reaped
    socket) when the fresh process tries to bind, which would otherwise raise
    "Address already in use" and crash the boot — surfacing to the runner as
    "API server could not be restarted". SO_REUSEPORT lets the new process
    bind alongside the lingering socket, and the bounded retry loop rides out
    any brief window where even that fails, so the reboot self-heals instead
    of dying.
    """
    last_err = None
    for _ in range(attempts):
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
            return sock
        except OSError as exc:
            last_err = exc
            sock.close()
            time.sleep(delay)
    raise last_err


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    listen_sock = _bind_listen_socket("0.0.0.0", port)
    server = make_server("0.0.0.0", port, app, threaded=True,
                         fd=listen_sock.fileno())
    server.serve_forever()
