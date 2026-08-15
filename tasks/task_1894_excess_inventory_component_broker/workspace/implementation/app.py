"""Excess Inventory Component Broker API — Flask entry point."""

import os

from flask import Flask, g

import routes_a
import routes_b
import routes_c
import routes_d
from core import (
    LOCK,
    ApiError,
    ERR_INVALID_REQUEST,
    authenticate,
    err_response,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _before():
        LOCK.acquire()
        g._locked = True
        authenticate()

    @app.teardown_request
    def _teardown(exc):
        if getattr(g, "_locked", False):
            g._locked = False
            LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return err_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return err_response(ERR_INVALID_REQUEST, 404, "Unknown route")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return err_response(ERR_INVALID_REQUEST, 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _internal(e):
        return err_response("ERR_INTERNAL", 500, "Internal server error")

    routes_a.register(app)
    routes_b.register(app)
    routes_c.register(app)
    routes_d.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
