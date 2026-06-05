"""Family Court Divorce API — Flask entry point.

Boots with EMPTY in-memory stores. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over
state and NOTHING is seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.guidelines import bp as guidelines_bp
from routes.cases import bp as cases_bp
from routes.parties import bp as parties_bp
from routes.pleadings import bp as pleadings_bp
from routes.disclosures import bp as disclosures_bp
from routes.parenting_plans import bp as parenting_plans_bp
from routes.mediation import bp as mediation_bp
from routes.support_orders import bp as support_orders_bp
from routes.court_orders import bp as court_orders_bp
from routes.hearings import bp as hearings_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(guidelines_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(pleadings_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(parenting_plans_bp)
    app.register_blueprint(mediation_bp)
    app.register_blueprint(support_orders_bp)
    app.register_blueprint(court_orders_bp)
    app.register_blueprint(hearings_bp)

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
        return error_response(ERR_INVALID_REQUEST, getattr(e, "description", None) or "Bad request", 422)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            code = e.code or 500
            if code == 404 or code == 405:
                return error_response(ERR_NOT_FOUND, e.description or str(e), 404)
            if code == 400:
                return error_response(ERR_INVALID_REQUEST, e.description or str(e), 422)
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), code)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
