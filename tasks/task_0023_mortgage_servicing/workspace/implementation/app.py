"""Mortgage Servicing API — Flask entry point.

Fresh boot: empty stores, no seeding, no on-disk persistence.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException, MethodNotAllowed, NotFound

import response
from errors import ApiError


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.borrowers import bp as borrowers_bp
    from routes.loans import bp as loans_bp
    from routes.forbearance import bp as forbearance_bp
    from routes.escrow import bp as escrow_bp
    from routes.foreclosure import bp as foreclosure_bp
    from routes.pmi import bp as pmi_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(borrowers_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(forbearance_bp)
    app.register_blueprint(escrow_bp)
    app.register_blueprint(foreclosure_bp)
    app.register_blueprint(pmi_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(NotFound)
    def _handle_not_found(err):
        return response.error("ERR_RESOURCE_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(MethodNotAllowed)
    def _handle_method_not_allowed(err):
        return response.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err: HTTPException):
        return response.error("ERR_INVALID_REQUEST", err.description or err.name, err.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        import traceback

        traceback.print_exc(file=sys.stderr)
        return response.error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
