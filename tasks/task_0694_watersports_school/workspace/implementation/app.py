"""Watersports School API — entry point.

In-memory storage only (see db.py). No entity data is seeded at startup; the
store is empty on every boot and tests build all state via the declared API.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response

# Import route blueprints.
from routes.catalog import bp as catalog_bp
from routes.people import bp as people_bp
from routes.enrollments import bp as enrollments_bp
from routes.sessions import bp as sessions_bp
from routes.bookings import bp as bookings_bp
from routes.rentals import bp as rentals_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(rentals_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface any unexpected error as a validation error rather than a 500 HTML page.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", f"unexpected error: {e}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
