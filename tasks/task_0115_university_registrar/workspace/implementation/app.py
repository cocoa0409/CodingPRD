"""University Registrar API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
(via start.sh) before every test, so there is no carry-over state and nothing
is ever seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response

from routes.terms import bp as terms_bp
from routes.programs import bp as programs_bp
from routes.courses import bp as courses_bp
from routes.instructors import bp as instructors_bp
from routes.sections import bp as sections_bp
from routes.students import bp as students_bp
from routes.appointments import bp as appointments_bp
from routes.enrollments import bp as enrollments_bp
from routes.holds import bp as holds_bp
from routes.swaps import bp as swaps_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)

    for bp in (
        terms_bp, programs_bp, courses_bp, instructors_bp, sections_bp,
        students_bp, appointments_bp, enrollments_bp, holds_bp, swaps_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        # Unknown method on a known path: surface as a not-found-style rejection.
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response("ERR_VALIDATION", "Malformed request", 400)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_VALIDATION", e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    import time as _time

    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation this process is relaunched on the SAME port
    # immediately after the previous server is killed; the old listener socket can
    # linger for a few milliseconds, making the initial bind transiently fail with
    # "Address already in use". Retry the bind briefly so a fresh boot is robust
    # instead of crashing and being reported by the harness as "could not be
    # restarted". Once the bind succeeds, app.run blocks and serves normally.
    _deadline = _time.time() + 10.0
    while True:
        try:
            app.run(host="0.0.0.0", port=port, debug=False,
                    use_reloader=False, threaded=True)
            break
        except OSError:
            if _time.time() >= _deadline:
                raise
            _time.sleep(0.2)
