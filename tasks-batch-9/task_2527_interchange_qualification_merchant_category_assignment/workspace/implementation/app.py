"""Interchange Qualification & Merchant Category Assignment API.

Flask entry point. All state lives in memory and starts empty on every boot:
nothing here seeds, preloads or hardcodes any entity.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ERR_INVALID_REQUEST, ApiError
from store import store

import routes_audit
import routes_clearing
import routes_incentive
import routes_merchant
import routes_ref
import routes_windows


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_windows.bp)
    app.register_blueprint(routes_merchant.bp)
    app.register_blueprint(routes_clearing.bp)
    app.register_blueprint(routes_incentive.bp)
    app.register_blueprint(routes_audit.bp)

    @app.before_request
    def _begin_request():
        # Per-request bookkeeping: a row mutated by several cascade hops inside
        # one request advances its version exactly once.
        g._touched = set()
        store.lock.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _end_request(_exc=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                store.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error_response(
            ERR_INVALID_REQUEST,
            exc.description or "The request could not be routed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response(ERR_INVALID_REQUEST, "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
