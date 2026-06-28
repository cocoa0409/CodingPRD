"""Eating-Disorder Treatment API — Flask entry point.

Registers all blueprints, installs the standard error handlers, and runs the
server in the foreground on 0.0.0.0:$PORT (default 10000).

State lives entirely in memory (db.store) and is created empty on every process
start. Nothing is seeded or preloaded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.facilities import bp as facilities_bp
from routes.patients import bp as patients_bp
from routes.assessments import bp as assessments_bp
from routes.admissions import bp as admissions_bp
from routes.authorizations import bp as authorizations_bp
from routes.treatment_plans import bp as treatment_plans_bp
from routes.meals import bp as meals_bp
from routes.family_discharge import bp as family_discharge_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(facilities_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(admissions_bp)
    app.register_blueprint(authorizations_bp)
    app.register_blueprint(treatment_plans_bp)
    app.register_blueprint(meals_bp)
    app.register_blueprint(family_discharge_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> treat as a generic not-found in the standard envelope.
        return error_response(errors.ERR_INVALID_REQUEST, 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_INVALID_REQUEST, 405, "Method not allowed.")

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, 400, "Bad request.")

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        return error_response(errors.ERR_INVALID_REQUEST, exc.code or 400, exc.description or "Error.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard: surface in the standard envelope rather than HTML.
        return error_response(errors.ERR_INVALID_REQUEST, 500, "Internal server error.")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
