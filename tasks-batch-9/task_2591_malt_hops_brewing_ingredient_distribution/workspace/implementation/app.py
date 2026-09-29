"""Malt & Hops brewing ingredient distribution API.

Boots with a completely empty store: nothing is seeded, preloaded or
hardcoded.  Every entity is created by callers through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response
from routes import (
    brewers,
    clock,
    coldchain,
    contracts,
    malt,
    offers,
    orders,
    programs,
    varieties,
    yeast,
)

BLUEPRINTS = (
    brewers.bp,
    programs.bp,
    varieties.bp,
    contracts.bp,
    offers.bp,
    malt.bp,
    yeast.bp,
    orders.bp,
    coldchain.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        # Requests mutate several resources at once and every propagation is
        # synchronous, so they are serialised.
        db.LOCK.acquire()

    @app.teardown_request
    def _release(_exc=None):
        try:
            db.LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_INVALID_REQUEST", "Unknown route", 404)
        if status == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this route", 405
            )
        if status in (400, 415, 422):
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed", status
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
