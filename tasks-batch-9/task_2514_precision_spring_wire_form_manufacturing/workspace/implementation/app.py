"""Precision Spring & Wire Form Manufacturing API — Flask application factory.

Storage is process-local and in memory (see store.py); nothing is seeded.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import envelope
import routes_commercial
import routes_core
import routes_designs
import routes_runs
import routes_shop
from errors import ApiError

# One writer at a time: every request mutates a shared in-memory graph.
_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_designs.bp)
    app.register_blueprint(routes_shop.bp)
    app.register_blueprint(routes_runs.bp)
    app.register_blueprint(routes_commercial.bp)

    @app.before_request
    def _acquire():
        _LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.error(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return envelope.error(ApiError("ERR_NOT_FOUND",
                                          "The requested resource does not exist."))
        if err.code == 405:
            return envelope.error(ApiError("ERR_METHOD_NOT_ALLOWED",
                                          "That method is not allowed here."))
        if err.code == 400:
            return envelope.error(ApiError("ERR_INVALID_REQUEST",
                                          "The request could not be parsed."))
        return envelope.error(ApiError("ERR_INTERNAL", err.description or "Error",
                                       http_status=err.code or 500))

    @app.errorhandler(Exception)
    def _unhandled(err):
        return envelope.error(ApiError("ERR_INTERNAL", "Unexpected server error."))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
