"""Workers-Comp Claims API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over state.
NO entity is seeded at startup — every entity is created through the API.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.employers import bp as employers_bp
from routes.policies import bp as policies_bp
from routes.workers import bp as workers_bp
from routes.claims import bp as claims_bp
from routes.injury_reports import bp as injury_reports_bp
from routes.wage_statements import bp as wage_statements_bp
from routes.reserves import bp as reserves_bp
from routes.benefit_payments import bp as benefit_payments_bp
from routes.impairment_ratings import bp as impairment_ratings_bp
from routes.rtw_offers import bp as rtw_offers_bp
from routes.ime_orders import bp as ime_orders_bp
from routes.experience_mods import bp as experience_mods_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(employers_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(workers_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(injury_reports_bp)
    app.register_blueprint(wage_statements_bp)
    app.register_blueprint(reserves_bp)
    app.register_blueprint(benefit_payments_bp)
    app.register_blueprint(impairment_ratings_bp)
    app.register_blueprint(rtw_offers_bp)
    app.register_blueprint(ime_orders_bp)
    app.register_blueprint(experience_mods_bp)
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
