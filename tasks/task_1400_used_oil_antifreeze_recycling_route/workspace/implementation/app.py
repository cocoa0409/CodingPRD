"""Entry point: Flask app, error handlers, blueprint registration.

Storage is in-memory only (Python dicts in db.py). The store starts empty on
every boot; no seed data is ever loaded. The server reads the PORT env var
(default 10000), binds 0.0.0.0, and runs in the foreground.
"""

import os

from flask import Flask, jsonify

import db
from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import (
    blend_batches,
    customers,
    drivers,
    facilities,
    manifests,
    prices_clock,
    route_stops,
    routes_bp,
    screenings,
    spills,
    tank_sites,
    tanks,
    tickets,
)

API_PREFIX = "/recycle-routes"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        customers,
        tank_sites,
        tanks,
        drivers,
        routes_bp,
        route_stops,
        screenings,
        tickets,
        facilities,
        manifests,
        blend_batches,
        spills,
        prices_clock,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ApiError(ERR_INVALID_REQUEST, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ApiError(ERR_INVALID_REQUEST, "Method not allowed", 405))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(ApiError(ERR_INVALID_REQUEST, "Malformed request", 400))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
