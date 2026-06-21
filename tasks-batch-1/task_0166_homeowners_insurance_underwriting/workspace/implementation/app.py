"""Homeowners Insurance Underwriting API — Flask entry point.

In-memory only. No seeding at startup: the store starts empty on every boot and
tests build all state via the API surface.
"""
import os
import socket

# --- Boot-latency guard (no effect on API behaviour) ---
# Werkzeug's dev-server startup calls socket.getfqdn() to print its cosmetic
# "Running on http://<host>" banner. On hosts whose .local hostname does not
# reverse-resolve, that call blocks ~5s on a DNS timeout, which under the
# per-test-server harness (server rebooted before every test, 8 rounds in
# parallel) pushes boot past the runner's startup window and yields flaky
# "server could not be restarted" / connection-reset failures. Short-circuit
# the hostname lookups to a constant so boot is instant and deterministic.
# This touches only the startup banner; no request path uses these calls.
_orig_getfqdn = socket.getfqdn


def _fast_getfqdn(name=""):  # noqa: D401
    if name in ("", "0.0.0.0", "::"):
        return "localhost"
    return name


socket.getfqdn = _fast_getfqdn

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response
from routes.underwriters import bp as underwriters_bp
from routes.properties import bp as properties_bp
from routes.risk_assessments import bp as risk_assessments_bp
from routes.inspectors import bp as inspectors_bp
from routes.inspections import bp as inspections_bp
from routes.applications import bp as applications_bp
from routes.endorsements import bp as endorsements_bp
from routes.quotes import bp as quotes_bp
from routes.policies import bp as policies_bp
from routes.payments import bp as payments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(underwriters_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(risk_assessments_bp)
    app.register_blueprint(inspectors_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(endorsements_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(payments_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — generic not found.
        return error_response("ERR_INVALID_REQUEST", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        return error_response("ERR_INVALID_REQUEST", exc.description or "Error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard so the server never leaks a stack trace / non-enveloped body.
        return error_response("ERR_INVALID_REQUEST", "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
