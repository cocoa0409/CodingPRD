"""Tax-Prep Storefront & Refund Advance API — Flask entry point.

In-memory storage only (db.py). NOTHING is seeded at startup: every entity is
constructed by callers through the declared endpoints. The logical clock starts
at exactly 2026-05-01T00:00:00Z on each fresh boot (PRD §3.9)."""
import os

from flask import Flask

import errors
from response import error_response
from routes.offices import bp as offices_bp
from routes.credentials import bp as credentials_bp
from routes.preparers import bp as preparers_bp
from routes.clients import bp as clients_bp
from routes.appointments import bp as appointments_bp
from routes.returns import bp as returns_bp
from routes.documents import bp as documents_bp
from routes.audit_protections import bp as audit_protections_bp
from routes.refund_transfers import bp as refund_transfers_bp
from routes.refund_advances import bp as refund_advances_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(offices_bp)
    app.register_blueprint(credentials_bp)
    app.register_blueprint(preparers_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(audit_protections_bp)
    app.register_blueprint(refund_transfers_bp)
    app.register_blueprint(refund_advances_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
