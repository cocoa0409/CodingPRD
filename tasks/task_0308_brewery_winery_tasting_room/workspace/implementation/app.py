"""Entry point: app factory, error handlers, blueprint registration.

In-memory only. Nothing is seeded at startup; the store is empty on boot and
every entity is created through the declared API surface.
"""
import os
import socket

# --- Boot-speed hardening (self-contained, no dependency on the runner) ---
# Under per-test-server isolation the server is restarted before every test, and
# under the 8-round concurrent stability sweep eight interpreters can bind their
# sockets at the same instant. Two stdlib calls in Werkzeug's dev server can each
# stall a fresh boot long enough to blow the runner's restart-poll window:
#   1. HTTPServer.server_bind() calls socket.getfqdn("0.0.0.0"), which on macOS
#      blocks several seconds on a reverse-DNS (PTR) lookup that has no answer.
#   2. werkzeug.serving log_startup() calls get_interface_ip(), opening a UDP
#      socket to an arbitrary external address purely to print a banner URL.
# Neither result affects request handling. We neutralize both here so the boot is
# fast and deterministic even if the runner's sitecustomize injection is absent.
_real_getfqdn = socket.getfqdn
_UNSPECIFIED = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED:
        return "localhost"
    return _real_getfqdn(name)


socket.getfqdn = _fast_getfqdn

try:  # Suppress the dev-server startup banner (and its get_interface_ip probe).
    import werkzeug.serving as _wz_serving

    _wz_serving.BaseWSGIServer.log_startup = lambda self: None
except Exception:  # pragma: no cover - banner suppression is best-effort
    pass

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.wineries import bp as wineries_bp
from routes.batches import bp as batches_bp
from routes.products import bp as products_bp
from routes.releases import bp as releases_bp
from routes.members import bp as members_bp
from routes.memberships import bp as memberships_bp
from routes.shipments import bp as shipments_bp
from routes.tasting_orders import bp as tasting_orders_bp
from routes.reservations import bp as reservations_bp
from routes.distribution_orders import bp as distribution_orders_bp
from routes.ledger import bp as ledger_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        wineries_bp, batches_bp, products_bp, releases_bp, members_bp,
        memberships_bp, shipments_bp, tasting_orders_bp, reservations_bp,
        distribution_orders_bp, ledger_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {exc}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
