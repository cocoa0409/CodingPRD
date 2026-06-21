"""Medicaid Eligibility & Annual Redetermination API — Flask entry point.

Boots with EMPTY in-memory stores. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over
state and nothing is seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.config import bp as config_bp
from routes.households import bp as households_bp
from routes.applications import bp as applications_bp
from routes.enrollments import bp as enrollments_bp
from routes.redeterminations import bp as redeterminations_bp
from routes.appeals import bp as appeals_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(households_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(redeterminations_bp)
    app.register_blueprint(appeals_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            code = e.code or 500
            err_id = ERR_NOT_FOUND if code == 404 else ERR_INVALID_REQUEST
            return error_response(err_id, e.description or str(e), code)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
