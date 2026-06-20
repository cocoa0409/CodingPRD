"""Entry point for the Natural Gas Utility Billing API.

Registers blueprints, installs the global error handler that emits the standard
error envelope (PRD §2.2), and runs the Flask app bound to 0.0.0.0:$PORT.

NO entity data is seeded at startup — the in-memory store begins empty (except
the singleton Clock config) and tests build all state via the API surface.
"""

import os
import socket

from flask import Flask

# --- Startup robustness: avoid a slow reverse-DNS lookup at boot ---
# Werkzeug's WSGI server runs `socket.getfqdn(host)` to set `server_name` when
# it starts. On some hosts (notably macOS with an mDNS ".local" hostname),
# resolving the local FQDN blocks for ~5 seconds per boot. Under per-test-server
# isolation the server is restarted before every test, so this 5s penalty is
# paid hundreds of times and can push boot past the runner's restart window
# (manifesting as flaky "server could not be restarted" / BadStatusLine errors).
# This shim short-circuits the lookup for the bind addresses we use; it does not
# affect any request handling or API behavior.
_orig_getfqdn = socket.getfqdn


def _fast_getfqdn(name=""):  # pragma: no cover - startup only
    if name in ("", "0.0.0.0", "::", "localhost", "127.0.0.1"):
        return "localhost"
    try:
        return _orig_getfqdn(name)
    except Exception:
        return name


socket.getfqdn = _fast_getfqdn

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.rate_schedules import bp as rate_schedules_bp
from routes.pga_schedules import bp as pga_schedules_bp
from routes.accounts import bp as accounts_bp
from routes.meters import bp as meters_bp
from routes.meter_reads import bp as meter_reads_bp
from routes.bills import bp as bills_bp
from routes.payments import bp as payments_bp
from routes.budget_plans import bp as budget_plans_bp
from routes.deposits import bp as deposits_bp
from routes.low_income_credits import bp as low_income_credits_bp
from routes.service_orders import bp as service_orders_bp
from routes.tickets import bp as tickets_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(rate_schedules_bp)
    app.register_blueprint(pga_schedules_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(meters_bp)
    app.register_blueprint(meter_reads_bp)
    app.register_blueprint(bills_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(budget_plans_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(low_income_credits_bp)
    app.register_blueprint(service_orders_bp)
    app.register_blueprint(tickets_bp)

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
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
