"""Carnival Midway Ride Safety API — Flask entry point.

All collections are mounted under /midway. Storage is in-memory only; the
process boots with an empty store every time.
"""
import os

from flask import Flask, jsonify

import db
from errors import ApiError
from response import error_response

from routes.fairs import bp as fairs_bp
from routes.rides import bp as rides_bp
from routes.inspectors import bp as inspectors_bp
from routes.appointments import bp as appointments_bp
from routes.permits import bp as permits_bp
from routes.staff import bp as staff_bp
from routes.certs import bp as certs_bp
from routes.days import bp as days_bp
from routes.checklists import bp as checklists_bp
from routes.cycles import bp as cycles_bp
from routes.redemptions import bp as redemptions_bp
from routes.products import bp as products_bp
from routes.sales import bp as sales_bp
from routes.weather import bp as weather_bp
from routes.incidents import bp as incidents_bp
from routes.shifts import bp as shifts_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    blueprints = [
        fairs_bp,
        rides_bp,
        inspectors_bp,
        appointments_bp,
        permits_bp,
        staff_bp,
        certs_bp,
        days_bp,
        checklists_bp,
        cycles_bp,
        redemptions_bp,
        products_bp,
        sales_bp,
        weather_bp,
        incidents_bp,
        shifts_bp,
        clock_bp,
    ]
    for blueprint in blueprints:
        app.register_blueprint(blueprint, url_prefix="/midway")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", 404, "The requested resource was not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", 404, "The requested resource was not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INVALID_REQUEST", 500, "Unexpected server error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
