"""Bankruptcy filing API — application entrypoint.

Registers all blueprints, installs the global ApiError handler that emits the
standard error envelope, and starts a Flask server bound to 0.0.0.0 on the
PORT environment variable (default 10000) per INSTRUCTION.md.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError, make_error
from response import error as error_response
from routes.cases import cases_bp
from routes.claims import claims_bp
from routes.clock import clock_bp
from routes.collection_actions import collection_actions_bp
from routes.creditors import creditors_bp
from routes.debtors import debtors_bp
from routes.plans import plans_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(debtors_bp)
    app.register_blueprint(creditors_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(collection_actions_bp)
    app.register_blueprint(clock_bp)

    # -----------------------------------------------------------------
    # Error handlers
    # -----------------------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Werkzeug's default 404 (path not matched) — translate to ERR_NOT_FOUND.
        err = make_error("ERR_NOT_FOUND", "Route not found.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(405)
    def handle_405(exc):
        err = make_error("ERR_BAD_REQUEST", "Method not allowed.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(400)
    def handle_400(exc):
        err = make_error("ERR_BAD_REQUEST", "Malformed request.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        # Wrap any unhandled werkzeug exception in our envelope.
        code = exc.code or 500
        if code == 404:
            return handle_404(exc)
        if code == 405:
            return handle_405(exc)
        err = make_error("ERR_BAD_REQUEST", exc.description or "HTTP exception")
        return error_response(err.error_id, err.message, code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        # Last-resort handler so the server never leaks a non-envelope error.
        return error_response("ERR_BAD_REQUEST", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
