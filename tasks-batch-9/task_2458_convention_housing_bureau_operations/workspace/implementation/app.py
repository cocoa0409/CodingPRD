"""Convention Housing Bureau Operations API — Flask application entrypoint.

Storage is in-memory only and empty on every boot: nothing is seeded, preloaded
or hardcoded.  The process is started fresh by start.sh before every test.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, ERROR_STATUS
from store import STORE
from routes import (
    attendees,
    attrition,
    blocks,
    clock,
    events,
    hotels,
    invoices,
    reporting,
    reservations,
    subblocks,
    vendors,
)

BLUEPRINTS = (
    events.bp,
    hotels.bp,
    blocks.bp,
    subblocks.bp,
    attendees.bp,
    reservations.bp,
    reporting.bp,
    attrition.bp,
    vendors.bp,
    invoices.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # One global lock per request keeps the cascades atomic under a threaded
    # server without any of the routes needing to know about concurrency.
    @app.before_request
    def _acquire_lock():
        STORE.lock.acquire()
        g._housing_lock_held = True

    @app.teardown_request
    def _release_lock(exc=None):
        if g.pop("_housing_lock_held", False):
            try:
                STORE.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "the requested resource does not exist", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "the method is not allowed for this path", 405
            )
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "the request could not be parsed", 400)
        if exc.code == 415:
            return error_response("ERR_INVALID_REQUEST", "unsupported media type", 400)
        return error_response(
            "ERR_INTERNAL", exc.description or "unexpected error", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response(
            "ERR_INTERNAL", "unexpected server error: %s" % exc, ERROR_STATUS["ERR_INTERNAL"]
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
