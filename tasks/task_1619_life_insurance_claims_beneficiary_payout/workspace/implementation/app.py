"""Entry point: Flask app, error handlers, route registration.

The store starts completely empty on every boot; all state is built through
the declared API surface. The logical clock starts at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, jsonify

from helpers import ApiError, error_response
from store import db  # noqa: F401  (ensures the store/clock are initialized)

import routes_core
import routes_claims
import routes_final


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_final.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return (
            jsonify(
                {
                    "meta": {},
                    "response_type": "error",
                    "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
                }
            ),
            500,
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
