"""Overnight Summer Camp API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot. No seeding.
Reads PORT from the environment, binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

from routes.clock import bp as clock_bp
from routes.guardians import bp as guardians_bp
from routes.camps import bp as camps_bp
from routes.sessions import bp as sessions_bp
from routes.cabins import bp as cabins_bp
from routes.staff import bp as staff_bp
from routes.campers import bp as campers_bp
from routes.health_forms import bp as health_forms_bp
from routes.applications import bp as applications_bp
from routes.financial_aid import bp as financial_aid_bp
from routes.payments import bp as payments_bp
from routes.activities import bp as activities_bp
from routes.canteen import bp as canteen_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(guardians_bp)
    app.register_blueprint(camps_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(cabins_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(campers_bp)
    app.register_blueprint(health_forms_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(financial_aid_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(activities_bp)
    app.register_blueprint(canteen_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # Method not allowed on a known path -> treat as not found in our envelope.
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Bad request.", 400)
        return response.error("ERR_INVALID_REQUEST", str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INVALID_REQUEST", "Unexpected error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
