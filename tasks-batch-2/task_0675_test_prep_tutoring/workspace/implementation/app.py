"""Test-Prep Tutoring API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot. No seeding.
Reads PORT from the environment, binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

from routes.courses import bp as courses_bp
from routes.instructors import bp as instructors_bp
from routes.cohorts import bp as cohorts_bp
from routes.students import bp as students_bp
from routes.enrollments import bp as enrollments_bp
from routes.practice_attempts import bp as practice_attempts_bp
from routes.installment_plans import bp as installment_plans_bp
from routes.guarantee_claims import bp as guarantee_claims_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(courses_bp)
    app.register_blueprint(instructors_bp)
    app.register_blueprint(cohorts_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(practice_attempts_bp)
    app.register_blueprint(installment_plans_bp)
    app.register_blueprint(guarantee_claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # Method not allowed on a known path -> not found in our envelope.
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Bad request.", 422)
        return response.error("ERR_INVALID_REQUEST", str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INVALID_REQUEST", "Unexpected error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
