"""Wealth Management & Trust Accounting API — entry point.

In-memory store; no seeding. Boots clean on every invocation.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.parties import bp as parties_bp
from routes.trusts import bp as trusts_bp
from routes.appointments import bp as appointments_bp
from routes.accounts import bp as accounts_bp
from routes.distributions import bp as distributions_bp
from routes.k1s import bp as k1s_bp
from routes.filings import bp as filings_bp
from routes.gst import bp as gst_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(parties_bp)
    app.register_blueprint(trusts_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(k1s_bp)
    app.register_blueprint(filings_bp)
    app.register_blueprint(gst_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_VALIDATION", "Malformed request.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", "Unexpected error: " + str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
