"""Touring Motorsports Series Promotion API — Flask entry point.

State lives in process-local dictionaries (see db.py): nothing is persisted and
nothing is seeded, so every boot starts from an empty store.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError, MESSAGES, STATUS
from response import error_response

_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register(app)

    @app.before_request
    def _serialize_requests():
        _lock.acquire()

    @app.teardown_request
    def _release_requests(exc):
        try:
            _lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "the requested resource does not exist", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_NOT_FOUND", "the method is not allowed for this resource", 404
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", MESSAGES.get("ERR_INVALID_REQUEST", "invalid request"), 422
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "invalid request", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "internal server error: %s" % exc, 500)

    return app


app = create_app()
_ = STATUS


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
