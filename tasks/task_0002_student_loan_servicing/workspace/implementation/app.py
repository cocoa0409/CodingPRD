"""Student Loan Servicing API — Flask app entry point.

Boots cleanly on every fresh process. NO entity seeding at startup; every entity
the tests need is constructed via the declared API surface.
"""
from __future__ import annotations

import os
import sys

from flask import Flask, request

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import extract_auth
from response import error as error_response
from routes.borrowers import bp as borrowers_bp
from routes.clock import bp as clock_bp
from routes.discharge_applications import bp as discharge_applications_bp
from routes.employment_certifications import bp as employment_certifications_bp
from routes.loans import bp as loans_bp
from routes.payments import bp as payments_bp
from routes.pslf_trackers import bp as pslf_trackers_bp
from routes.repayment_plans import bp as repayment_plans_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Disable Flask default redirect for trailing slashes — tests want exact path matching.
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth_gate():
        # Handle auth on every request. Errors are caught by the APIError handler.
        try:
            extract_auth()
        except APIError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)
        return None

    # Register blueprints
    app.register_blueprint(borrowers_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(repayment_plans_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(employment_certifications_bp)
    app.register_blueprint(pslf_trackers_bp)
    app.register_blueprint(discharge_applications_bp)
    app.register_blueprint(clock_bp)

    # Centralized error handlers
    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(_):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_generic(exc):
        # Log to stderr to aid debugging in the harness
        print(f"[UNHANDLED EXCEPTION] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return error_response(ERR_INVALID_REQUEST, f"Server error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Threaded server so per-test-server requests don't serialize unnecessarily.
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
