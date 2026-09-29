"""Inpatient Psychiatric Admission API — Flask application entrypoint.

Storage is entirely in memory (plain Python dicts in store.py) and starts empty on
every boot: no entity data is seeded, preloaded or hardcoded anywhere.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import register_routes

# All requests are serialized so that cascade chains are applied atomically.
_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.before_request
    def _acquire():
        _LOCK.acquire()

    @app.teardown_request
    def _release(_exc=None):
        try:
            _LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_INVALID_REQUEST", "resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", exc.description or "bad request", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "request failed", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INVALID_REQUEST", f"unexpected server error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
