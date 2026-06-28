"""Float-Spa API entry point. In-memory store; logical clock defaults to
2026-01-01T00:00:00Z on a fresh boot. NO seeding of any kind."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response
from routes.misc import bp as misc_bp
from routes.memberships import bp as memberships_bp
from routes.tanks import bp as tanks_bp
from routes.orientations import bp as orientations_bp
from routes.bookings import bp as bookings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(misc_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(tanks_bp)
    app.register_blueprint(orientations_bp)
    app.register_blueprint(bookings_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Map any other werkzeug HTTPException into the standard envelope.
        status = err.code or 500
        return error_response("ERR_INVALID_REQUEST", err.description or "Error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
