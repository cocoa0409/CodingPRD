"""Outdoor Gear & Sports Rental API — Flask entry point.

In-memory storage only; no seeding at startup. The store starts empty on every
boot; tests construct all entities via the declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error as error_response

from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.gear_units import bp as gear_units_bp
from routes.reservations import bp as reservations_bp
from routes.assessments import bp as assessments_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(gear_units_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(misc_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Malformed JSON body etc. surface as a validation error.
        if e.code == 400:
            return error_response(errors.ERR_VALIDATION, "Malformed request", 400)
        return error_response(errors.ERR_VALIDATION, e.description or "Error", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(errors.ERR_VALIDATION, "Internal error: " + str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
