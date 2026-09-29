"""Membership Campground / RV Club Program service — Flask entry point.

Storage is entirely in memory (plain dicts in store.py). Nothing is seeded at
startup: every entity is created by clients through the declared endpoints, and a
fresh process always begins with thirteen empty collections and the logical clock
at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import clock
import response
import routes_capital
import routes_catalog
import routes_parks
import routes_reservations
import routes_transfers
import store
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    store.reset()
    clock.reset()

    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_parks.bp)
    app.register_blueprint(routes_reservations.bp)
    app.register_blueprint(routes_transfers.bp)
    app.register_blueprint(routes_capital.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        body = response.error_body(exc.error_id, exc.message)
        return body, exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error_body("ERR_INVALID_REQUEST", "resource not found"), 404
        if exc.code == 405:
            return (response.error_body("ERR_INVALID_REQUEST",
                                        "method not allowed on this path"), 405)
        if exc.code and exc.code < 500:
            return (response.error_body("ERR_INVALID_REQUEST",
                                        exc.description or "invalid request"), 400)
        return (response.error_body("ERR_INVALID_REQUEST",
                                    "internal error"), exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_body("ERR_INVALID_REQUEST", "internal error: %s" % exc), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
