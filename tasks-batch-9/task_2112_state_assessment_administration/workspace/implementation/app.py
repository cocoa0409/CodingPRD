"""State Assessment Administration API — entry point.

Boots a fresh, empty in-memory store on every process start; nothing is seeded.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response, gen_request_id
from routes import BLUEPRINTS

# Requests mutate a shared in-memory graph, so they are serialised: a request
# either applies all of its side effects or none of them.
_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_request():
        _REQUEST_LOCK.acquire()
        g.lock_held = True
        g.request_id = gen_request_id()
        g.touched_ids = set()

    @app.teardown_request
    def _end_request(exception=None):
        if getattr(g, "lock_held", False):
            g.lock_held = False
            _REQUEST_LOCK.release()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested path does not exist.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.", 405
            )
        if exc.code and 400 <= exc.code < 500:
            return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.", exc.code)
        return error_response("ERR_INTERNAL", exc.description or "Internal error.", exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
