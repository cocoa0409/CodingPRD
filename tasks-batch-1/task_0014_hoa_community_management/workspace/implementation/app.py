"""HOA Community Management API entry point.

Boots fresh on every invocation -- in-memory store starts empty per the
test harness's per-test-server isolation.
"""
from __future__ import annotations

import os

from flask import Flask

from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    HTTP_STATUS,
)
from response import error as error_response
from routes.acc_requests import bp as acc_bp
from routes.assessments import bp as assessments_bp
from routes.clock import bp as clock_bp
from routes.communities import bp as communities_bp
from routes.elections import bp as elections_bp
from routes.liens import bp as liens_bp
from routes.owners import bp as owners_bp
from routes.payments import bp as payments_bp
from routes.properties import bp as properties_bp
from routes.reserves import bp as reserves_bp
from routes.violations import bp as violations_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Avoid pretty-printing for deterministic responses; preserve insertion order
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(communities_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(acc_bp)
    app.register_blueprint(elections_bp)
    app.register_blueprint(liens_bp)
    app.register_blueprint(reserves_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        body, status = error_response(err.error_id, err.message, err.http_status)
        return body, status

    @app.errorhandler(404)
    def handle_404(_err):
        body, status = error_response(
            ERR_NOT_FOUND, "Route not found", HTTP_STATUS[ERR_NOT_FOUND]
        )
        return body, status

    @app.errorhandler(405)
    def handle_405(_err):
        body, status = error_response(
            ERR_NOT_FOUND, "Method not allowed", HTTP_STATUS[ERR_NOT_FOUND]
        )
        return body, status

    @app.errorhandler(400)
    def handle_400(_err):
        body, status = error_response(
            ERR_INVALID_REQUEST, "Bad request", HTTP_STATUS[ERR_INVALID_REQUEST]
        )
        return body, status

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Last-resort handler — surface as ERR_INVALID_REQUEST 400 since
        # the catalog lacks a generic 500 entry.
        body, status = error_response(
            ERR_INVALID_REQUEST, f"Server error: {err}",
            HTTP_STATUS[ERR_INVALID_REQUEST]
        )
        return body, status

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
