"""General Practice EHR & Visit API — Flask entry point.

Boots with empty in-memory stores on every fresh process. The test harness
restarts this process before each test (per-test-server isolation), so there is
no carry-over state and nothing is ever seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.providers import bp as providers_bp
from routes.patients import bp as patients_bp
from routes.cpt_codes import bp as cpt_codes_bp
from routes.visits import bp as visits_bp
from routes.prescriptions import bp as prescriptions_bp
from routes.referrals import bp as referrals_bp
from routes.portal_accounts import bp as portal_accounts_bp
from routes.hedis import bp as hedis_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(providers_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(cpt_codes_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(portal_accounts_bp)
    app.register_blueprint(hedis_bp)
    app.register_blueprint(clock_bp)

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
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
