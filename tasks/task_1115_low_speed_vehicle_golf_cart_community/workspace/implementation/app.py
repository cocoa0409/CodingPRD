"""Entry point: Flask app, route registration, error handlers.

No seeding: all stores start empty; every entity is created via the declared
API surface. Logical clock starts at 2026-05-01T00:00:00Z (see db.py).
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.communities import bp as communities_bp
from routes.permit_holders import bp as permit_holders_bp
from routes.vehicles import bp as vehicles_bp
from routes.registrations import bp as registrations_bp
from routes.inspections import bp as inspections_bp
from routes.insurance import bp as insurance_bp
from routes.routes_passes import bp as routes_passes_bp
from routes.charging import bp as charging_bp
from routes.fleet import bp as fleet_bp
from routes.violations import bp as violations_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (communities_bp, permit_holders_bp, vehicles_bp, registrations_bp,
               inspections_bp, insurance_bp, routes_passes_bp, charging_bp,
               fleet_bp, violations_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        from errors import err_not_found
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        from errors import err_not_found
        return error_response(err_not_found("Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        from errors import err_validation
        return error_response(err_validation(str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
