"""Unscripted Casting & Participant Agreements API — Flask entry point.

Storage is in-memory only and every collection starts empty on every boot;
nothing is ever seeded, preloaded or persisted to disk.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_agreements
import routes_blocks
import routes_casting
import routes_production
import store
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_production.bp)
    app.register_blueprint(routes_production.clock_bp)
    app.register_blueprint(routes_casting.bp)
    app.register_blueprint(routes_agreements.bp)
    app.register_blueprint(routes_blocks.bp)

    @app.before_request
    def _before_request():
        # version/updated_at move at most once per record per request
        g.touched = set()
        # every request is serialised: the store is a plain dict graph
        store.write_lock.acquire()

    @app.teardown_request
    def _teardown_request(exc=None):
        try:
            store.write_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND"))
        if error.code == 405:
            return error_response(ApiError("ERR_METHOD_NOT_ALLOWED"))
        if error.code == 400:
            return error_response(ApiError("ERR_INVALID_REQUEST"))
        return error_response(ApiError("ERR_INTERNAL", str(error)))

    @app.errorhandler(Exception)
    def _unhandled(error):  # pragma: no cover - defensive
        return error_response(ApiError("ERR_INTERNAL", str(error)))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
