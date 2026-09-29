"""Hardwood Flooring Mill & Kiln Drying API.

A single Flask process holding all state in memory. Nothing is persisted and
nothing is seeded: a fresh boot starts with every collection empty, which is
exactly what the per-test-server harness relies on.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db as store
from errors import ApiError
from response import error_response
from routes.byproducts import bp as byproducts_bp
from routes.charges import bp as charges_bp
from routes.config import bp as config_bp
from routes.grading import bp as grading_bp
from routes.lots import bp as lots_bp
from routes.prefinish import bp as prefinish_bp
from routes.receipts import bp as receipts_bp
from routes.warranty import bp as warranty_bp

BLUEPRINTS = (
    config_bp,
    receipts_bp,
    charges_bp,
    lots_bp,
    grading_bp,
    prefinish_bp,
    byproducts_bp,
    warranty_bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_store_lock():
        store.LOCK.acquire()
        g._store_lock_held = True

    @app.teardown_request
    def _release_store_lock(_exc=None):
        if g.pop("_store_lock_held", False):
            try:
                store.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Request payload failed schema validation.", 400)
        if exc.code in (404, 405):
            return error_response("ERR_NOT_FOUND", "Resource was not found.", 404)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover -- defensive
        return error_response("ERR_INVALID_REQUEST", "Request failed: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
