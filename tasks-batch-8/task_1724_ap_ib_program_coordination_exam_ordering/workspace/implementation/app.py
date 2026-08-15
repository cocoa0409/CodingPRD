"""AP/IB Exam Coordination API — Flask entry point."""
import os
import threading

from flask import Flask

from errors import ApiError
from response import error_response

# The in-memory store is process-global; a single request lock makes every
# mutation atomic against concurrent test-harness requests.
_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    @app.before_request
    def _acquire_request_lock():
        _REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release_request_lock(exc=None):
        try:
            _REQUEST_LOCK.release()
        except RuntimeError:
            pass

    from routes import (
        applications, authorizations, clock, courses, cycles, irregularities,
        orders, proctors, registrations, sessions, students, teachers,
    )
    for mod in (
        clock, cycles, courses, teachers, authorizations, students, applications,
        registrations, orders, sessions, proctors, irregularities,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", f"unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
