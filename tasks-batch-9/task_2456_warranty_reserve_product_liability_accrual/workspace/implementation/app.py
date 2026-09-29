"""Warranty Reserve & Product Liability Accrual service.

Boots completely empty on every invocation: no entity data is ever seeded,
preloaded or hardcoded.  Storage is process-local Python dictionaries only.
"""

import os

from flask import Flask, g

import store
from errors import ApiError
from response import error_response
from routes import (
    accruals,
    catalog,
    clock,
    contracts,
    field_actions,
    liability,
    periods,
    suppliers,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        periods,
        catalog,
        accruals,
        field_actions,
        contracts,
        suppliers,
        liability,
        clock,
    ):
        app.register_blueprint(module.bp)

    # The store starts empty; nothing is seeded here or anywhere else.
    store.reset()

    @app.before_request
    def _serialise_request():
        # One global lock per request keeps every cascade and every version bump
        # deterministic even when the WSGI server serves requests on threads.
        store.LOCK.acquire()
        g.lock_held = True

    @app.teardown_request
    def _release_request(_exception=None):
        if g.pop("lock_held", False):
            store.LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _not_found(_error):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return error_response(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed for this route.", 405
        )

    @app.errorhandler(400)
    def _bad_request(_error):
        return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", str(error), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
