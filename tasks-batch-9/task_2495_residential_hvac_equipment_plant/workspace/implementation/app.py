"""Residential HVAC equipment plant API.

A single Flask process holding all state in memory. Nothing is seeded: every
row is created through the declared endpoints, so a fresh boot is an empty plant.
"""

import os

from flask import Flask

import web
from errors import ERROR_STATUS, ApiError
from routes_design import bp as design_bp
from routes_ops import bp as ops_bp
from routes_supply import bp as supply_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(design_bp)
    app.register_blueprint(supply_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return web.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return web.error_response(
            "ERR_NOT_FOUND", "No such resource.", ERROR_STATUS["ERR_NOT_FOUND"]
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return web.error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "Method not allowed for this resource.",
            ERROR_STATUS["ERR_METHOD_NOT_ALLOWED"],
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return web.error_response(exc.error_id, exc.message, exc.http_status)
        return web.error_response("ERR_INVALID_REQUEST", str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
