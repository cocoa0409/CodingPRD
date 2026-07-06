"""Refill & Zero-Waste Store API — Flask entry point.

In-memory storage only (see store.py). No entities are seeded at startup: every
resource is constructed by tests through the declared API surface. The server is
relaunched before each test, so a fresh boot must start with empty state.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Unknown routes / methods: keep the standard envelope shape.
        return response.error("ERR_VALIDATION", exc.description or exc.name, exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        body = {
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(exc)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
