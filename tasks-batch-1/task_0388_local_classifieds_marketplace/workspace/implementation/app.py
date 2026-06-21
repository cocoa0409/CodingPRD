"""Local Classifieds Marketplace API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.members import bp as members_bp
from routes.categories import bp as categories_bp
from routes.listings import bp as listings_bp
from routes.conversations import bp as conversations_bp
from routes.offers import bp as offers_bp
from routes.spots import bp as spots_bp
from routes.meetups import bp as meetups_bp
from routes.flags import bp as flags_bp
from routes.saved_searches import bp as saved_searches_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        members_bp,
        categories_bp,
        listings_bp,
        conversations_bp,
        offers_bp,
        spots_bp,
        meetups_bp,
        flags_bp,
        saved_searches_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        # Map framework-level HTTP errors to the standard envelope.
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Error.", exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
