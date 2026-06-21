"""USCIS Case Management API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test, so there is no carry-over state.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.registration import bp as registration_bp
from routes.users import bp as users_bp
from routes.cases import bp as cases_bp
from routes.biometrics import bp as biometrics_bp
from routes.rfes import bp as rfes_bp
from routes.interviews import bp as interviews_bp
from routes.visa_bulletin import bp as visa_bulletin_bp
from routes.workload import bp as workload_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(registration_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(biometrics_bp)
    app.register_blueprint(rfes_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(visa_bulletin_bp)
    app.register_blueprint(workload_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
