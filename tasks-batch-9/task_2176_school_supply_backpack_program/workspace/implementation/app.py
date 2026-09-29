"""School Supply Drive & Backpack Program API — entry point."""
import os
import sys
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import response as resp  # noqa: E402
from errors import ApiError  # noqa: E402
from routes.cash import bp as cash_bp  # noqa: E402
from routes.cycles import bp as cycles_bp  # noqa: E402
from routes.donations import bp as donations_bp  # noqa: E402
from routes.events import bp as events_bp  # noqa: E402
from routes.kitspecs import bp as kitspecs_bp  # noqa: E402
from routes.schools import bp as schools_bp  # noqa: E402
from routes.students import bp as students_bp  # noqa: E402


_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    # Every request mutates a shared in-memory store; serialising them keeps
    # each operation atomic so optimistic-concurrency races resolve cleanly.
    @app.before_request
    def _acquire_lock():
        _REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            _REQUEST_LOCK.release()
        except RuntimeError:
            pass

    for blueprint in (schools_bp, kitspecs_bp, cycles_bp, donations_bp,
                      cash_bp, events_bp, students_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return resp.error("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return resp.error("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed for this path.", 405)
        if exc.code and 400 <= exc.code < 500:
            return resp.error("ERR_INVALID_REQUEST",
                              exc.description or "Malformed request.", 400)
        return resp.error("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return resp.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
