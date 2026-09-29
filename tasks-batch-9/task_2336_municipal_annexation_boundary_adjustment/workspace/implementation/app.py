"""Municipal Annexation & Boundary Adjustment API.

A single Flask process holding every record in memory. Nothing is seeded at boot:
the store is empty and the logical clock reads exactly 2026-08-01T00:00:00Z until a
test moves it with POST /_clock/set_current_utc.
"""

import os

from flask import Flask, g

from db import db
from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_routes(app)

    @app.before_request
    def _acquire_lock():
        # One global re-entrant lock: every request mutates the shared in-memory store.
        db.lock.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release_lock(_exception=None):
        if g.pop("_store_locked", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _not_found(_error):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(Exception)
    def _unexpected(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
