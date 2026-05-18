"""Flask application entry point.

Personal Tax Filing API — implements PRD task_0135.
Reads PORT from env (default 10000), binds 0.0.0.0.
"""
from __future__ import annotations

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from errors import ApiError
from response import error as error_response

# Route blueprints.
from routes.amendments import bp as amendments_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.clock import bp as clock_bp
from routes.credits import bp as credits_bp
from routes.efilings import bp as efilings_bp
from routes.estimated_payments import bp as estimated_payments_bp
from routes.income_documents import bp as income_documents_bp
from routes.schedules import bp as schedules_bp
from routes.tax_returns import bp as tax_returns_bp
from routes.taxpayers import bp as taxpayers_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register all blueprints.
    app.register_blueprint(taxpayers_bp)
    app.register_blueprint(tax_returns_bp)
    app.register_blueprint(income_documents_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(credits_bp)
    app.register_blueprint(efilings_bp)
    app.register_blueprint(amendments_bp)
    app.register_blueprint(estimated_payments_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(clock_bp)

    @app.post("/__test__/reset")
    def __test_reset():
        """Wipe all in-memory state between tests (test-only helper).

        The PRD's virtual clock advances forward only, so without a
        per-test reset the clock would accumulate across the suite and
        reject otherwise-valid future-dated payment dates.
        """
        from db import store
        from flask import jsonify

        store.reset()
        return jsonify({"ok": True}), 200

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Per scaffold: a path that does not match any route returns
        # ERR_RESOURCE_NOT_FOUND (404). For more-specific path-id misses
        # routes raise ERR_TAXPAYER_NOT_FOUND / ERR_RETURN_NOT_FOUND
        # directly via the helper functions.
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_INVALID_STATE", "Method not allowed.", 409)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error_response(
            "ERR_INVALID_INPUT", exc.description or "HTTP error", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_INPUT", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
