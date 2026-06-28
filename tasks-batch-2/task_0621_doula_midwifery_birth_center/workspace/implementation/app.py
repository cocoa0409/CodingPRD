"""Midwifery Birth Center API — Flask entry point.

In-memory only; the store starts EMPTY on every boot. No seeding.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.episodes import bp as episodes_bp
from routes.visits import bp as visits_bp
from routes.oncall import bp as oncall_bp
from routes.bookings import bp as bookings_bp
from routes.billing import bp as billing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(episodes_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(oncall_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> resource-not-found semantics.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
