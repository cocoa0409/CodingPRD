"""Sunroom & Patio Enclosure API — Flask entry point.

In-memory storage only; nothing seeded at startup. Each process boot starts
with empty stores and the logical clock at its default (2026-04-01T00:00:00Z).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from routes.homeowners import bp as homeowners_bp
from routes.projects import bp as projects_bp
from routes.measurements import bp as measurements_bp
from routes.quotes import bp as quotes_bp
from routes.financing import bp as financing_bp
from routes.permits import bp as permits_bp
from routes.manufacture import bp as manufacture_bp
from routes.crews import bp as crews_bp
from routes.install_jobs import bp as install_jobs_bp
from routes.inspections import bp as inspections_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(homeowners_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(measurements_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(financing_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(manufacture_bp)
    app.register_blueprint(crews_bp)
    app.register_blueprint(install_jobs_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — surface as ERR_NOT_FOUND envelope.
        return response.error(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        # Map any other werkzeug HTTP errors (e.g. 400 malformed) to the envelope.
        status = exc.code or 500
        if status == 400:
            return response.error(errors.ERR_INVALID_REQUEST, "Bad request.", 400)
        return response.error(errors.ERR_INVALID_REQUEST, str(exc), status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
