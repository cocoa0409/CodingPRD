"""Livestock Auction Sale Barn API - entry point.

The store is EMPTY at boot: no entity is seeded, preloaded or hardcoded. Every
row a caller needs is created through the declared endpoints.
"""
import errno
import os
import socket
import sys
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error as error_response
from errors import ApiError

from routes.bids import bp as bids_bp
from routes.buyer_registrations import bp as buyer_registrations_bp
from routes.consignments import bp as consignments_bp
from routes.infrastructure import bp as infrastructure_bp
from routes.inspections import bp as inspections_bp
from routes.lots import bp as lots_bp
from routes.manifests import bp as manifests_bp
from routes.money_routes import bp as money_bp
from routes.pen_moves import bp as pen_moves_bp
from routes.sale_days import bp as sale_days_bp
from routes.weigh_tickets import bp as weigh_tickets_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (infrastructure_bp, sale_days_bp, consignments_bp, lots_bp,
                      weigh_tickets_bp, pen_moves_bp, buyer_registrations_bp,
                      bids_bp, money_bp, inspections_bp, manifests_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code in (404, 405):
            return error_response("ERR_RESOURCE_NOT_FOUND", 404,
                                  "The requested resource does not exist.")
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", 400,
                                  "The request body could not be parsed.")
        return error_response("ERR_INVALID_REQUEST", exc.code or 400,
                              exc.description or "Request failed.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", 400, str(exc))

    return app


app = create_app()


def _bind(host, port, attempts=40, delay=0.25):
    """Pre-bind the listening socket ourselves.

    Under --isolation per-test-server the harness kill -9's the previous server
    and spawns the replacement immediately, without waiting for the LISTEN
    socket to be released. Werkzeug turns a bind failure into SystemExit, which
    no try/except around app.run() can catch, so we own the bind and retry
    EADDRINUSE here before handing the file descriptor to Werkzeug.
    """
    last = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(128)
            return sock
        except OSError as exc:
            sock.close()
            if exc.errno not in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                raise
            last = exc
            time.sleep(delay)
    raise last if last is not None else OSError("could not bind")


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    from werkzeug.serving import make_server
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(0)


if __name__ == "__main__":
    main()
