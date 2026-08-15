"""Ferry Service Scheduling & Ticketing API — Flask entry point.

In-memory only (db.py module-level dicts). No seeding at startup; every entity
is constructed through the declared API surface. Boots empty on every launch.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.routes import bp as routes_bp
from routes.vessels import bp as vessels_bp
from routes.fare_schedules import bp as fare_schedules_bp
from routes.sailings import bp as sailings_bp
from routes.customers import bp as customers_bp
from routes.bookings import bp as bookings_bp
from routes.standby import bp as standby_bp
from routes.crew import bp as crew_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock_bp, routes_bp, vessels_bp, fare_schedules_bp, sailings_bp,
               customers_bp, bookings_bp, standby_bp, crew_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_err):
        from errors import ERR_NOT_FOUND
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(_err):
        from errors import ERR_NOT_FOUND
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(500)
    def handle_500(err):
        from errors import ERR_NOT_FOUND
        return error_response(ApiError(ERR_NOT_FOUND, "Internal error", 404))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
