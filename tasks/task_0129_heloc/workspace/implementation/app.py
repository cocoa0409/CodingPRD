"""Flask application entry point for the HELOC Servicing API."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from db import reset_store, store
from errors import ApiError
from response import error as error_response
from utils import iso_now

# Blueprints.
from routes.admin import bp as admin_bp
from routes.borrowers import bp as borrowers_bp
from routes.heloc_children import bp as heloc_children_bp
from routes.helocs import bp as helocs_bp
from routes.properties import bp as properties_bp
from routes.senior_liens import bp as senior_liens_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(borrowers_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(senior_liens_bp)
    app.register_blueprint(helocs_bp)
    app.register_blueprint(heloc_children_bp)
    app.register_blueprint(admin_bp)

    @app.get("/__test__/now")
    def test_now():
        """Test helper: return the current logical clock as ISO 8601 UTC."""
        return jsonify({"now": iso_now(store.now())}), 200

    @app.post("/__test__/reset")
    def test_reset():
        """Test helper: wipe all in-memory state so the test suite can
        start each scenario from a clean baseline.  Not part of the
        PRD's public API surface."""
        reset_store()
        return jsonify({"ok": True}), 200

    # ── Error handlers ─────────────────────────────────────────────────

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_INVALID_STATE", "Method Not Allowed", 409)

    @app.errorhandler(HTTPException)
    def handle_http(exc: HTTPException):
        return error_response(
            "ERR_VALIDATION_FAILED",
            exc.description or "HTTP error",
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_VALIDATION_FAILED", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
