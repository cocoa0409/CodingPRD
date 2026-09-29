"""Contract Shuttle Service API — entry point.

In-memory only: every collection in store.py starts empty on each boot and no
entity is ever seeded, preloaded or hardcoded at startup.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import store
from envelope import error_response
from errors import ApiError
from routes.clock import bp as clock_bp
from routes.contracts import bp as contracts_bp
from routes.fleet import bp as fleet_bp
from routes.memos import bp as memos_bp
from routes.ondemand import bp as ondemand_bp
from routes.renewals import bp as renewals_bp
from routes.reports import bp as reports_bp
from routes.route_design import bp as route_design_bp
from routes.trips import bp as trips_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (contracts_bp, route_design_bp, fleet_bp, trips_bp,
                      ondemand_bp, reports_bp, memos_bp, renewals_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _serialize_requests():
        store.LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release_lock(exc=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            store.LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "No such endpoint."))
        if err.code == 405:
            return error_response(
                ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path."))
        return error_response(
            ApiError("ERR_INTERNAL", err.description or "Request failed",
                     http_status=err.code or 500))

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - safety net
        return error_response(ApiError("ERR_INTERNAL", "Internal server error."))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
