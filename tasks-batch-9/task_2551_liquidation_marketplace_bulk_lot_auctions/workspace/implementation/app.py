"""Liquidation Marketplace Bulk Lot Auctions API — in-memory Flask server.

Storage is process-local and starts completely empty on every boot: the test
harness relaunches this process before each test, and no entity data is ever
seeded, preloaded or persisted anywhere.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import bids, claims, listings, lots, negotiations, ops, orders, reference

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (reference, lots, listings, bids, negotiations, orders, claims, ops):
        app.register_blueprint(module.bp)

    @app.before_request
    def _serialize_request():
        _LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release_request(_exc=None):
        if g.pop("_holds_lock", False):
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return response.error_response(err)

    @app.errorhandler(404)
    def _handle_missing(_err):
        return response.error_response(ApiError("ERR_NOT_FOUND", "Resource not found."))

    @app.errorhandler(405)
    def _handle_method(_err):
        return response.error_response(
            ApiError("ERR_INVALID_REQUEST", "Method not allowed for this path.")
        )

    @app.errorhandler(HTTPException)
    def _handle_http(err):
        status = err.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL"
        return response.error_response(
            ApiError(error_id, err.description, http_status=status)
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return response.error_response(
            ApiError("ERR_INTERNAL", "Unexpected server error: %s" % err, http_status=500)
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
