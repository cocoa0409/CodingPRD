"""Flask application entry point.

Binds blueprints, registers the global error handler that maps ApiError
into the standard envelope, and starts the server on PORT/0.0.0.0 per
INSTRUCTION.md.
"""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import config as cfg
from errors import ApiError
from response import error as error_response

# Route blueprints
from routes.accounts import bp as accounts_bp
from routes.acat_transfers import bp as acat_bp
from routes.admin import bp as admin_bp
from routes.customers import bp as customers_bp
from routes.options_approvals import bp as oa_bp
from routes.orders import bp as orders_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(oa_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(acat_bp)
    app.register_blueprint(admin_bp)

    # ── Test-only helpers ──────────────────────────────────────────────
    @app.get("/__test__/now")
    def _test_now():
        from db import store
        from utils import iso_utc

        return jsonify({"now": iso_utc(store.now())}), 200

    @app.post("/__test__/reset")
    def _test_reset():
        from db import reset_store

        reset_store()
        return jsonify({"ok": True}), 200

    # ── Error mapping ──────────────────────────────────────────────────
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_CUSTOMER_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_VALIDATION", "Method Not Allowed", 422)

    @app.errorhandler(HTTPException)
    def _handle_http(exc):
        return error_response("ERR_VALIDATION", exc.description or "HTTP error", exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_VALIDATION", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=cfg.HOST, port=cfg.PORT, threaded=True)
