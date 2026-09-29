"""Wireless Site Acquisition & Zoning API.

Storage is in-memory only and starts EMPTY on every boot: no seeding, no
preloaded fixtures, no persistence between processes.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import LOCK
from errors import ApiError
from response import error
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_lock():
        LOCK.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release_lock(exc=None):
        if g.pop("_store_locked", False):
            LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED",
                         "The HTTP method is not allowed for this path.", 405)
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request is malformed.", 400)
        return error("ERR_INTERNAL", exc.description or "Request failed.",
                     exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
