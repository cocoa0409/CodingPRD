"""Campus Housing & Dorm Assignment API — Flask entry point.

In-memory only. No persistence, no seeding. Every process boot starts empty.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from routes.buildings import bp as buildings_bp
from routes.students import bp as students_bp
from routes.cycles import bp as cycles_bp
from routes.applications import bp as applications_bp
from routes.roommates import bp as roommates_bp
from routes.assignments import bp as assignments_bp
from routes.meal_plans import bp as meal_plans_bp
from routes.waitlist import bp as waitlist_bp
from routes.damage_charges import bp as damage_charges_bp
from routes.incidents import bp as incidents_bp
from routes.break_housing import bp as break_housing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(buildings_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(roommates_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(meal_plans_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(damage_charges_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(break_housing_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error_response(
            errors.ERR_NOT_FOUND, "Resource not found.", 404
        )

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_response(
            errors.ERR_NOT_FOUND, "Method not allowed.", 404
        )

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        # Fall back to a generic invalid-request for other HTTP errors (e.g.
        # malformed JSON surfaced by Flask before our handlers run).
        if exc.code == 400:
            return response.error_response(
                errors.ERR_INVALID_REQUEST, "Bad request.", 400
            )
        return response.error_response(
            errors.ERR_INVALID_REQUEST, exc.description or "Request error.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error_response(
            "ERR_INTERNAL", "Internal server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
