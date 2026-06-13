"""TSA PreCheck / Global Entry Enrollment API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process before
every test (per-test-server isolation), so there is no carry-over state and
nothing is seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INTERNAL, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.clock import bp as clock_bp
from routes.programs import bp as programs_bp
from routes.applicants import bp as applicants_bp
from routes.centers import bp as centers_bp
from routes.applications import bp as applications_bp
from routes.vetting import bp as vetting_bp
from routes.appointments import bp as appointments_bp
from routes.biometrics import bp as biometrics_bp
from routes.ktn import bp as ktn_bp
from routes.appeals import bp as appeals_bp
from routes.redress import bp as redress_bp
from routes.audit import bp as audit_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(centers_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(vetting_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(biometrics_bp)
    app.register_blueprint(ktn_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(redress_bp)
    app.register_blueprint(audit_bp)

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
        return error_response(ERR_INVALID_REQUEST, "Bad request", 422)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            code = e.code or 500
            if code == 404:
                return error_response(ERR_NOT_FOUND, "Route not found", 404)
            if code == 405:
                return error_response(ERR_NOT_FOUND, "Method not allowed", 404)
            if code == 400:
                return error_response(ERR_INVALID_REQUEST, "Bad request", 422)
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), code)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response(ERR_INTERNAL, f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
