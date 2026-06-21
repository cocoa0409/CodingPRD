"""Entry point for the Ambulance EMS Billing API.

Registers blueprints, installs the global error handler that emits the standard
error envelope (PRD §2.2), and runs the Flask app bound to 0.0.0.0:$PORT.

NO entity data is seeded at startup — the in-memory store begins empty and tests
build all state via the API surface.
"""

import os
import socket

from flask import Flask

# --- Startup robustness: avoid a slow reverse-DNS lookup at boot ---
# Werkzeug's WSGI server runs `socket.getfqdn(host)` to set `server_name` when
# it starts. On some hosts (notably macOS with an mDNS ".local" hostname),
# resolving the local FQDN blocks for ~5 seconds per boot. Under per-test-server
# isolation the server is restarted before every test, so this penalty is paid
# many times and can push boot past the runner's restart window (manifesting as
# flaky "server could not be restarted" / BadStatusLine errors). This shim
# short-circuits the lookup for the bind addresses we use; it does not affect
# any request handling or API behavior.
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

from routes.agencies import bp as agencies_bp
from routes.payer_plans import bp as payer_plans_bp
from routes.patients import bp as patients_bp
from routes.fleet import bp as fleet_bp
from routes.unit_assignments import bp as unit_assignments_bp
from routes.transports import bp as transports_bp
from routes.claims import bp as claims_bp
from routes.remittances import bp as remittances_bp
from routes.payments import bp as payments_bp
from routes.adjustments import bp as adjustments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(agencies_bp)
    app.register_blueprint(payer_plans_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(unit_assignments_bp)
    app.register_blueprint(transports_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(remittances_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(adjustments_bp)

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
        return error_response("ERR_INVALID_REQUEST", "Bad request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
