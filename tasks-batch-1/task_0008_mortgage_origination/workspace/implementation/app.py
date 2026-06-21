"""Mortgage Origination API — Flask entry point.

Fresh boot: empty stores, no seeding, no on-disk persistence.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException, MethodNotAllowed, NotFound

import response
from errors import (
    ApiError,
    ERR_APPLICATION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHORIZED,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register routes.
    from routes.clock import bp as clock_bp
    from routes.applicants import bp as applicants_bp
    from routes.loan_applications import bp as loan_applications_bp
    from routes.income_verifications import bp as income_bp
    from routes.asset_verifications import bp as asset_bp
    from routes.appraisals import bp as appraisals_bp
    from routes.title_searches import bp as title_bp
    from routes.rate_locks import bp as rate_locks_bp
    from routes.disclosures import bp as disclosures_bp
    from routes.udaap_checks import bp as udaap_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(loan_applications_bp)
    app.register_blueprint(income_bp)
    app.register_blueprint(asset_bp)
    app.register_blueprint(appraisals_bp)
    app.register_blueprint(title_bp)
    app.register_blueprint(rate_locks_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(udaap_bp)

    # ------------- Error handlers -------------
    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(NotFound)
    def _handle_not_found(err):
        # Unknown route → return ERR_APPLICATION_NOT_FOUND-ish? Better: 404 + INVALID_REQUEST.
        # The PRD's error table doesn't define a generic 404 for unknown routes.
        # We return ERR_APPLICATION_NOT_FOUND with HTTP 404 for path-id mismatches,
        # but truly unknown paths get a generic 404. Use ERR_INVALID_REQUEST style 404.
        return response.error("ERR_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(MethodNotAllowed)
    def _handle_method_not_allowed(err):
        return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err: HTTPException):
        return response.error("ERR_HTTP", err.description or err.name, err.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        import traceback

        traceback.print_exc(file=sys.stderr)
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
