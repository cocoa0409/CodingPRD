"""Uniform & Workwear Rental Program API — Flask entry point.

Boots a fresh in-memory store on every process start (no seeding, no disk
persistence). Registers all blueprints and the global error/JSON handlers.
"""
import os
import socket as _socket

# --- Fast-boot guard for the Werkzeug dev server's startup log line ---------
# On macOS, socket.getfqdn("0.0.0.0") blocks ~5s on a reverse-DNS (PTR) lookup
# that times out because the unspecified address has no hostname. Werkzeug's
# dev server calls getfqdn(host) during server_bind ONLY to compose its
# "Running on http://..." startup banner. Under per-test-server isolation the
# server reboots before every test, so that 5s stall is paid hundreds of times
# and, under a concurrent stability sweep on a loaded host, can push a boot past
# the runner's restart-poll window and surface as a spurious "could not be
# restarted". This shortcut returns "localhost" for the unspecified-address
# cases only; named addresses fall through to the real resolver unchanged. The
# result is used for nothing but that log line, so no API or test behavior is
# affected. (This mirrors the runner's bundled dnsboot patch, but is applied
# here so the speedup holds even when the runner does not inject it.)
_real_getfqdn = _socket.getfqdn
_UNSPECIFIED_HOSTS = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED_HOSTS:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn
# ---------------------------------------------------------------------------

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
import errors as err

from routes.accounts import bp as accounts_bp
from routes.wearers import bp as wearers_bp
from routes.catalog import bp as catalog_bp
from routes.garments import bp as garments_bp
from routes.assignments import bp as assignments_bp
from routes.routes_stops import bp as routes_stops_bp
from routes.service_visits import bp as service_visits_bp
from routes.service_charges import bp as service_charges_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(wearers_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(garments_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(routes_stops_bp)
    app.register_blueprint(service_visits_bp)
    app.register_blueprint(service_charges_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> resource-not-found envelope.
        return error_response(
            err.ERR_RESOURCE_NOT_FOUND, "Resource not found.", 404
        )

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(
            err.ERR_RESOURCE_NOT_FOUND, "Method not allowed for this path.", 405
        )

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(
            err.ERR_INVALID_REQUEST, "Malformed request.", 400
        )

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            code = e.code or 500
            if code == 404:
                return error_response(err.ERR_RESOURCE_NOT_FOUND, "Resource not found.", 404)
            if code == 400:
                return error_response(err.ERR_INVALID_REQUEST, "Malformed request.", 400)
            return error_response("ERR_INTERNAL", str(e), code)
        # Unexpected server fault.
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Silence the Werkzeug dev-server access log. Under per-test-server
    # isolation the server reboots and fields requests hundreds of times across
    # the concurrent 8-round sweep; the per-request stderr log line is pure
    # overhead on an already CPU-saturated host and is never read.
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
