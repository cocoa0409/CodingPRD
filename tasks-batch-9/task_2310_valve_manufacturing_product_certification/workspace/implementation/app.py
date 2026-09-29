"""Valve manufacturing and product certification API (Flask, in-memory store)."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ERROR_STATUS, ApiError
from response import error_response
from routes import (
    actuator_packages,
    clock,
    components,
    engineered_orders,
    foundries,
    foundry_qualifications,
    heat_lots,
    monogram_licenses,
    valve_models,
    valve_units,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        valve_models,
        foundries,
        foundry_qualifications,
        heat_lots,
        components,
        valve_units,
        actuator_packages,
        monogram_licenses,
        engineered_orders,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        status = exc.http_status or ERROR_STATUS.get(exc.error_id, 400)
        return error_response(exc.error_id, exc.message, status)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(HTTPException)
    def _handle_http(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "malformed request", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "request failed", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
