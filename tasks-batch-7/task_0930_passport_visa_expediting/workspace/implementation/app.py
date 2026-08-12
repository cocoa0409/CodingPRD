"""Entry point: blueprint registration, error handling and an EADDRINUSE-tolerant bind."""
import os
import socket
import sys
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import (
    appointment_routes,
    config_routes,
    courier_routes,
    document_routes,
    order_ops_routes,
    order_routes,
    rfe_routes,
    shipment_routes,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(config_routes.bp)
    app.register_blueprint(order_routes.bp)
    app.register_blueprint(order_ops_routes.bp)
    app.register_blueprint(document_routes.bp)
    app.register_blueprint(appointment_routes.bp)
    app.register_blueprint(courier_routes.bp)
    app.register_blueprint(rfe_routes.bp)
    app.register_blueprint(shipment_routes.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.error_response(
                "ERR_RESOURCE_NOT_FOUND", "The requested route does not exist.", 404
            )
        if exc.code == 405:
            return envelope.error_response(
                "ERR_VALIDATION", "The HTTP method is not allowed on this route.", 405
            )
        if exc.code == 400:
            return envelope.error_response(
                "ERR_VALIDATION", "The request body could not be parsed.", 400
            )
        return envelope.error_response(
            "ERR_VALIDATION", exc.description or "Request failed.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return envelope.error_response("ERR_VALIDATION", "Internal error: %s" % exc, 500)

    return app


app = create_app()


def _bind(host, port, attempts=40, delay=0.25):
    """Create the listening socket ourselves so a dying TIME_WAIT/LISTEN socket
    from the previous per-test server does not sys.exit(1) the new process."""
    last = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            sock.bind((host, port))
            sock.listen(256)
            sock.setblocking(True)
            return sock
        except OSError as exc:
            last = exc
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(delay)
    raise last


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    from werkzeug.serving import make_server

    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:  # pragma: no cover
        try:
            server.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
