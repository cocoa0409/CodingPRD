"""Performing Arts Center Season API.

Boots with a completely empty in-memory store on every process start: no seeding,
no persistence, no on-disk cache.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from envelope import error_response  # noqa: E402
from errors import ApiError  # noqa: E402
from routes import BLUEPRINTS  # noqa: E402
from store import store  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # A single process-wide lock serializes writes so the derived counters and the
    # append-only ledger stay consistent under concurrent requests.
    @app.before_request
    def _acquire_lock():
        store.lock.acquire()

    @app.teardown_request
    def _release_lock(_exception=None):
        try:
            store.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(_exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _handle_405(_exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this resource.", 405
        )

    @app.errorhandler(400)
    def _handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
            )
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
