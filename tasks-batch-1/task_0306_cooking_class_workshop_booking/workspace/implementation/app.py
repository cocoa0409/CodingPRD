"""Cooking Class & Culinary Workshop Booking API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.sessions import bp as sessions_bp
from routes.bookings import bp as bookings_bp
from routes.giftcards import bp as giftcards_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(giftcards_bp)

    # Serialize every request so that multi-entity cascades are atomic relative
    # to concurrent writers (the cascade either completes fully or not at all).
    # The lock is taken and released around the whole dispatch in a try/finally
    # so it can never leak across requests, even on disconnects or errors.
    base_wsgi_app = app.wsgi_app

    def _locked_wsgi(environ, start_response):
        with db.LOCK:
            return base_wsgi_app(environ, start_response)

    app.wsgi_app = _locked_wsgi

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        if isinstance(e, HTTPException):
            if e.code == 404:
                return error_response("ERR_NOT_FOUND", 404, "Resource not found")
            if e.code == 405:
                return error_response("ERR_NOT_FOUND", 404, "Method not allowed")
            return error_response("ERR_INVALID_REQUEST", e.code or 422, e.description or "HTTP error")
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
