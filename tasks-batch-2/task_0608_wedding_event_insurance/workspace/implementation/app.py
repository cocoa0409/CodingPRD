"""Wedding & Special-Event Insurance API — entry point.

In-memory store; no seeding. Boots cleanly on every process start.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.certificates import bp as certificates_bp
from routes.claims import bp as claims_bp
from routes.endorsements import bp as endorsements_bp
from routes.policies import bp as policies_bp
from routes.quote_items import bp as quote_items_bp
from routes.reference import bp as reference_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(quote_items_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(endorsements_bp)
    app.register_blueprint(claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path-resolution miss -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND", "method not allowed", 404)
        return error_response("ERR_INVALID_REQUEST", str(exc), exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard; surface as a generic 400 invalid request envelope.
        return error_response("ERR_INVALID_REQUEST", "unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
