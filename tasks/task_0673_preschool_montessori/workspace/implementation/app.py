"""Preschool & Montessori Program API — entry point.

Flask app: registers blueprints under the /montessori prefix, installs the
error handler that renders ApiError + framework errors in the standard
envelope, runs in the foreground on 0.0.0.0:$PORT (default 10000).

In-memory storage only; nothing seeded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes.clock import bp as clock_bp
from routes.tiers import bp as tiers_bp
from routes.classrooms import bp as classrooms_bp
from routes.students import bp as students_bp
from routes.applications import bp as applications_bp
from routes.enrollments import bp as enrollments_bp
from routes.payments import bp as payments_bp
from routes.refund_requests import bp as refund_requests_bp
from routes.staff_assignments import bp as staff_assignments_bp
from routes.assessment_records import bp as assessment_records_bp
from routes.conference_slots import bp as conference_slots_bp
from routes.observations import bp as observations_bp

API_PREFIX = "/montessori"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, tiers_bp, classrooms_bp, students_bp, applications_bp,
        enrollments_bp, payments_bp, refund_requests_bp, staff_assignments_bp,
        assessment_records_bp, conference_slots_bp, observations_bp,
    ):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(
            errors.ERR_NOT_FOUND, "Referenced resource does not exist.", 404
        )

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(
            errors.ERR_INVALID_REQUEST, "Method not allowed.", 400
        )

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(
            errors.ERR_INVALID_REQUEST, "Malformed request.", 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Let explicit HTTP exceptions fall through to their handlers above.
        if isinstance(exc, HTTPException):
            return exc
        return error_response(
            errors.ERR_INVALID_REQUEST, "Malformed request.", 400
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
