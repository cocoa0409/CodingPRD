"""MLS Listings & Buyer Matching API — Flask entry point.

In-memory store, resets every boot. No seeding.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.setup import bp as setup_bp
from routes.listings import bp as listings_bp
from routes.lockboxes import bp as lockboxes_bp
from routes.showings import bp as showings_bp
from routes.offers import bp as offers_bp
from routes.contingencies import bp as contingencies_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(setup_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(lockboxes_bp)
    app.register_blueprint(showings_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(contingencies_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_VALIDATION", e.code if e.code else 422, str(e))
        return error_response("ERR_VALIDATION", 422, "Unexpected error: " + str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
