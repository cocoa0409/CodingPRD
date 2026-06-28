"""Entry point: Flask app, error handlers, route registration.

In-memory only. No seeding. Fresh state on every process boot.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from errors import ERR_NOT_FOUND, ERR_VALIDATION

from routes.catalog import bp as catalog_bp
from routes.members import bp as members_bp
from routes.memberships import bp as memberships_bp
from routes.credit_packs import bp as credit_packs_bp
from routes.bookings import bp as bookings_bp
from routes.series import bp as series_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(credit_packs_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(series_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response(ERR_NOT_FOUND[0], "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND[0], "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_VALIDATION[0], "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", f"Unexpected error: {e}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
