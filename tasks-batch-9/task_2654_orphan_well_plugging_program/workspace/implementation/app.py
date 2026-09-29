"""Orphan Well Plugging Program API — application factory and entry point.

Storage is entirely in process memory (see store.py); no entity data is ever
seeded, preloaded or hardcoded at startup.  Every run begins with empty tables
and a logical clock pinned to 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_access
import routes_bids
import routes_clock
import routes_determinations
import routes_funding
import routes_jobs
import routes_operators
import routes_procurement
import routes_reclamation
import routes_transfers
import routes_wells
from envelope import error_response
from errors import ApiError

BLUEPRINTS = (
    routes_operators.bp,
    routes_wells.bp,
    routes_determinations.bp,
    routes_access.bp,
    routes_transfers.bp,
    routes_procurement.bp,
    routes_bids.bp,
    routes_jobs.bp,
    routes_reclamation.bp,
    routes_funding.bp,
    routes_clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "No such resource path.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "That method is not allowed on this path.",
                405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request body could not be read.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response(
            "ERR_INTERNAL", "Unexpected server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
