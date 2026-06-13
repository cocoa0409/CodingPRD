"""Window Cleaning & Pressure Washing API — Flask entry point.

Boots a fresh, empty in-memory store on every process start. No seeding.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response

from routes_accounts import bp as accounts_bp
from routes_quotes import bp as quotes_bp
from routes_agreements import bp as agreements_bp
from routes_fleet import bp as fleet_bp
from routes_visits import bp as visits_bp
from routes_billing import bp as billing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / resource -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Map any other werkzeug HTTP error into the standard envelope.
        if isinstance(exc, ApiError):  # pragma: no cover
            return error_response(exc.error_id, exc.message, exc.http_status)
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
