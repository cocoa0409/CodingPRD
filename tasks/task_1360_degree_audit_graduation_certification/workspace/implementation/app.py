"""Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store is in-memory and empty on every
boot — the test harness restarts the server per-test, so there is no carry-over.
"""

import os

from flask import Flask

import db
from errors import ApiError
from response import error_response
from routes import (
    applications,
    clock,
    courses_students,
    diplomas,
    enrollments,
    programs,
    student_programs,
    waivers,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(programs.bp)
    app.register_blueprint(courses_students.bp)
    app.register_blueprint(enrollments.bp)
    app.register_blueprint(student_programs.bp)
    app.register_blueprint(waivers.bp)
    app.register_blueprint(applications.bp)
    app.register_blueprint(diplomas.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "Route not found.")
        )

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "Method not allowed.")
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        # Surface as a 400 rather than 500 to keep the envelope consistent.
        return error_response(
            ApiError("ERR_INVALID_REQUEST", f"Unexpected error: {err}")
        )

    # Serialize all requests — the cascade is not thread-safe.
    @app.before_request
    def _acquire_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    return app


app = create_app()


if __name__ == "__main__":
    import errno
    import time

    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation the harness SIGKILLs the previous server
    # and immediately boots a fresh one on the same port. Under parallel load
    # the old listener's socket can outlive the kill by a beat, so a transient
    # EADDRINUSE on bind must be retried rather than allowed to kill the boot
    # (which surfaces as a spurious "could not be restarted").
    attempts = 0
    while True:
        try:
            app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
            break
        except OSError as exc:
            attempts += 1
            if exc.errno != errno.EADDRINUSE or attempts > 40:
                raise
            time.sleep(0.25)
