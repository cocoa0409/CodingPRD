"""Cosmetology & Beauty School API — Flask entry point.

In-memory only. State starts EMPTY on every boot and is wiped on restart.
No entity is seeded, preloaded, or hardcoded at startup.
"""
import os

from flask import Flask

import clock
import db
import errors
import middleware
import response

from routes.system import bp as system_bp
from routes.programs import bp as programs_bp
from routes.students import bp as students_bp
from routes.instructors import bp as instructors_bp
from routes.stations import bp as stations_bp
from routes.enrollments import bp as enrollments_bp
from routes.attendance import bp as attendance_bp
from routes.clinic_tickets import bp as clinic_tickets_bp
from routes.station_assignments import bp as station_assignments_bp
from routes.disbursements import bp as disbursements_bp
from routes.exam_applications import bp as exam_applications_bp
from routes.withdrawals import bp as withdrawals_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Fresh process => fresh, empty store + default logical clock.
    db.reset()
    clock.reset()

    @app.before_request
    def _auth():
        # Priority 1-2: establish auth context on every request (PRD 2.1).
        middleware.extract_auth()

    for bp in (
        system_bp, programs_bp, students_bp, instructors_bp, stations_bp,
        enrollments_bp, attendance_bp, clinic_tickets_bp, station_assignments_bp,
        disbursements_bp, exam_applications_bp, withdrawals_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def _api_error(e):
        return response.error(e)

    @app.errorhandler(404)
    def _not_found(e):
        return response.error(errors.not_found())

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return response.error(errors.ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, errors.ApiError):
            return response.error(e)
        return response.error(errors.ApiError("ERR_INTERNAL", 500, str(e)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
