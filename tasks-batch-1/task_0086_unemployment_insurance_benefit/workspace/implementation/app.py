"""Unemployment Insurance Benefit API — Flask entry point.

In-memory store only; starts empty on every boot. No seeding.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.parties import bp as parties_bp
from routes.claims import bp as claims_bp
from routes.determinations import bp as determinations_bp
from routes.weekly import bp as weekly_bp
from routes.overpayments import bp as overpayments_bp
from routes.appeals import bp as appeals_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(parties_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(determinations_bp)
    app.register_blueprint(weekly_bp)
    app.register_blueprint(overpayments_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path — treat as not found per the
        # API surface (no method-not-allowed code in the catalog).
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Map any other werkzeug HTTP error (e.g. malformed JSON 400) into the
        # envelope. Default to ERR_INVALID_REQUEST for 4xx.
        code = e.code or 500
        if code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if 400 <= code < 500:
            return error_response("ERR_INVALID_REQUEST", e.description or "Bad request.", code)
        return error_response("ERR_INTERNAL", e.description or "Server error.", code)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
