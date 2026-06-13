"""AML / KYC & Sanctions Screening API — entry point.

Registers all route blueprints, installs a global error handler that emits the
PRD §2.2 error envelope, and runs Flask on 0.0.0.0:$PORT (default 10000) in the
foreground. State is in-memory only and starts empty on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.customers import bp as customers_bp
from routes.screening import bp as screening_bp
from routes.accounts import bp as accounts_bp
from routes.cases import bp as cases_bp
from routes.filings import bp as filings_bp
from routes.lookback import bp as lookback_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(screening_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(filings_bp)
    app.register_blueprint(lookback_bp)
    app.register_blueprint(misc_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route: treat as resource-not-found per the envelope contract.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_uncaught(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(exc), exc.code or 422)
        # Defensive: never leak a stack trace as a non-enveloped 500.
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error.", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
