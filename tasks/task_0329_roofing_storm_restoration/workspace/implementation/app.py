"""Roofing Storm Restoration API — Flask entry point.

In-memory store, no seeding. Boots clean on every process start.
"""
import os

from flask import Flask, request

from errors import ApiError
import errors
from response import error_response

from routes.reference import bp as reference_bp
from routes.jobs import bp as jobs_bp
from routes.inspections import bp as inspections_bp
from routes.estimates import bp as estimates_bp
from routes.material_orders import bp as material_orders_bp
from routes.crew_assignments import bp as crew_assignments_bp
from routes.permits import bp as permits_bp
from routes.draws import bp as draws_bp
from routes.change_orders import bp as change_orders_bp
from routes.warranties import bp as warranties_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(estimates_bp)
    app.register_blueprint(material_orders_bp)
    app.register_blueprint(crew_assignments_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(draws_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(warranties_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / unmatched path id. Auth still can't be validated here,
        # but a genuinely unknown path is a not-found.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected failures as a generic invalid request rather than a
        # bare 500 HTML page, so the envelope is always JSON.
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
