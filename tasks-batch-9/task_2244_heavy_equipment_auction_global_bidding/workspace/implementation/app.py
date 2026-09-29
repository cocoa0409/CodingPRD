"""Heavy Equipment Auction & Global Bidding Platform — Flask entry point.

Storage is process-local and in memory only (see db.py); nothing is seeded, so a
fresh process always starts from an empty store.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from response import error_response
from routes.auctions import bp as auctions_bp
from routes.bidding import bp as bidding_bp
from routes.inspection import bp as inspection_bp
from routes.intake import bp as intake_bp
from routes.reference import bp as reference_bp
from routes.sales import bp as sales_bp
from routes.settlement import bp as settlement_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (reference_bp, intake_bp, inspection_bp, auctions_bp,
                      bidding_bp, sales_bp, settlement_bp):
        app.register_blueprint(blueprint)

    # Every request is serialised: each handler reads and writes several
    # collections and the invariants (deposit conservation, cap replay,
    # rollups) must never observe a half-applied mutation.
    @app.before_request
    def _acquire():
        db.lock.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(exc=None):
        if g.pop("_holds_lock", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this path.", 405)
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST",
                exc.description or "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
