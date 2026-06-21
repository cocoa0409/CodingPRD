"""Notary Commission & E-Notary Journal API — Flask entry point.

In-memory state, no seeding. The store starts empty on every boot; the test
harness restarts this process before every test (per-test-server isolation).
"""
import os

from flask import Flask, g

from errors import ApiError, ERROR_STATUS
from middleware import extract_identity
from response import error_response

from routes.jurisdictions import bp as jurisdictions_bp
from routes.notaries import bp as notaries_bp
from routes.bonds import bp as bonds_bp
from routes.renewals import bp as renewals_bp
from routes.sessions import bp as sessions_bp
from routes.journal_entries import bp as journal_entries_bp
from routes.complaints import bp as complaints_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _before():
        extract_identity()

    app.register_blueprint(jurisdictions_bp)
    app.register_blueprint(notaries_bp)
    app.register_blueprint(bonds_bp)
    app.register_blueprint(renewals_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(journal_entries_bp)
    app.register_blueprint(complaints_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request")

    @app.errorhandler(Exception)
    def _unhandled(e):
        # Surface unexpected failures as a generic 500 in the envelope shape.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
