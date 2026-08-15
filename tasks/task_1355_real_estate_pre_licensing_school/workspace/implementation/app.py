"""Main application entry point."""

import os
from flask import Flask
from errors import ApiError, error_response

app = Flask(__name__)

# Register blueprints
from routes.system import bp as system_bp
from routes.schools import bp as schools_bp
from routes.courses import bp as courses_bp
from routes.course_approvals import bp as course_approvals_bp
from routes.instructors import bp as instructors_bp
from routes.offerings import bp as offerings_bp
from routes.students import bp as students_bp
from routes.enrollments import bp as enrollments_bp
from routes.attendance import bp as attendance_bp
from routes.exam_attempts import bp as exam_attempts_bp
from routes.certificates import bp as certificates_bp
from routes.refund_requests import bp as refund_requests_bp
from routes.credit_reports import bp as credit_reports_bp
from routes.equivalency_grants import bp as equivalency_grants_bp
from routes.audit import bp as audit_bp

app.register_blueprint(system_bp)
app.register_blueprint(schools_bp)
app.register_blueprint(courses_bp)
app.register_blueprint(course_approvals_bp)
app.register_blueprint(instructors_bp)
app.register_blueprint(offerings_bp)
app.register_blueprint(students_bp)
app.register_blueprint(enrollments_bp)
app.register_blueprint(attendance_bp)
app.register_blueprint(exam_attempts_bp)
app.register_blueprint(certificates_bp)
app.register_blueprint(refund_requests_bp)
app.register_blueprint(credit_reports_bp)
app.register_blueprint(equivalency_grants_bp)
app.register_blueprint(audit_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_NOT_FOUND", "Not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_INTERNAL", str(e), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # The per-test harness kill -9s the previous server and immediately respawns
    # this one; under parallel sweeps the killed process's listening socket may
    # not be reaped yet when we reach bind(), producing a spurious EADDRINUSE.
    # Retry the bind so a transiently-busy port does not waste the runner's
    # 15s readiness window. app.run only returns after a clean shutdown, so the
    # loop engages solely on bind-time OSError.
    import time as _time

    _last_err = None
    for _attempt in range(40):
        try:
            app.run(host="0.0.0.0", port=port, debug=False)
            break
        except OSError as e:
            _last_err = e
            _time.sleep(0.5)
    else:
        if _last_err is not None:
            raise _last_err
