"""Pt Rehab API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test via start.sh, so there is no carry-over state. No entity
seeding happens at startup — every row tests need is created through the
declared API surface.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from response import error_response

from routes.clock import bp as clock_bp
from routes.patients import bp as patients_bp
from routes.therapists import bp as therapists_bp
from routes.veteran_referrals import bp as veteran_referrals_bp
from routes.plans_of_care import bp as plans_of_care_bp
from routes.evaluations import bp as evaluations_bp
from routes.authorization_grants import bp as authorization_grants_bp
from routes.visits import bp as visits_bp
from routes.home_exercise_programs import bp as home_exercise_programs_bp
from routes.mips_measures import bp as mips_measures_bp
from routes.discharge_assessments import bp as discharge_assessments_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(clock_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(therapists_bp)
    app.register_blueprint(veteran_referrals_bp)
    app.register_blueprint(plans_of_care_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(authorization_grants_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(home_exercise_programs_bp)
    app.register_blueprint(mips_measures_bp)
    app.register_blueprint(discharge_assessments_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_):
        return error_response(ERR_RESOURCE_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(ERR_RESOURCE_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(
            ERR_INVALID_REQUEST,
            str(getattr(e, "description", e)) or "bad request",
            400,
        )

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(
                ERR_INVALID_REQUEST,
                e.description or str(e),
                e.code or 500,
            )
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
