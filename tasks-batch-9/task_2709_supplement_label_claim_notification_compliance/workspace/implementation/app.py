"""Supplement Label Claim & Notification Compliance API.

Flask application factory and process entry point.  All state lives in
process-local dictionaries (see db.py); nothing is ever persisted to disk and
no entity is seeded at startup.
"""

import os

from flask import Flask, jsonify

import errors
import response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error_response(
            errors.ERR_VALIDATION, "No such route on this service.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error_response(
            errors.ERR_VALIDATION, "That method is not allowed on this route.", 405
        )

    @app.errorhandler(415)
    def handle_unsupported_media(exc):
        return response.error_response(
            errors.ERR_VALIDATION, "The request body must be JSON.", 422
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        if isinstance(exc, ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        return jsonify(
            {
                "meta": {},
                "response_type": "error",
                "data": {"error_id": "ERR_INTERNAL", "message": str(exc)},
            }
        ), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
