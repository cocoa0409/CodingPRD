"""Flight School & Pilot Training API — Flask entry point.

In-memory storage only (db.py). The store starts empty on every boot; nothing
is seeded. start.sh re-launches this process before every per-test run.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Route blueprints.
from routes.students import bp as students_bp
from routes.instructors import bp as instructors_bp
from routes.aircraft import bp as aircraft_bp
from routes.syllabi import bp as syllabi_bp
from routes.enrollments import bp as enrollments_bp
from routes.squawks import bp as squawks_bp
from routes.bookings import bp as bookings_bp
from routes.flight_logs import bp as flight_logs_bp
from routes.stage_checks import bp as stage_checks_bp
from routes.endorsements import bp as endorsements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (students_bp, instructors_bp, aircraft_bp, syllabi_bp,
               enrollments_bp, squawks_bp, bookings_bp, flight_logs_bp,
               stage_checks_bp, endorsements_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path resource not matched.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(exc), exc.code or 400)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
