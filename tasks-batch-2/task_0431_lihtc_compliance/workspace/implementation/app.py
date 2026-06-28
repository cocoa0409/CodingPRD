"""LIHTC Affordable Housing Compliance API — entry point.

Boots a fresh, empty in-memory store on every invocation (no seeding).
"""

import os

from flask import Flask, request

import middleware
import response
from errors import ApiError

from routes.clock_routes import bp as clock_bp
from routes.projects import bp as projects_bp
from routes.buildings import bp as buildings_bp
from routes.form8609s import bp as form8609s_bp
from routes.units import bp as units_bp
from routes.households import bp as households_bp
from routes.certifications import bp as certifications_bp
from routes.leases import bp as leases_bp
from routes.inspections import bp as inspections_bp
from routes.findings import bp as findings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _authenticate():
        # Every request requires the two auth headers (universal, incl. /_clock).
        middleware.authenticate()

    app.register_blueprint(clock_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(buildings_bp)
    app.register_blueprint(form8609s_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(households_bp)
    app.register_blueprint(certifications_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(findings_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_404(err):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(err):
        return response.error("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def _handle_400(err):
        return response.error("ERR_VALIDATION", "Malformed request", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error(err.error_id, err.message, err.http_status)
        return response.error("ERR_VALIDATION", "Unexpected error: " + str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
