"""Scholarly journal peer review and publishing API.

A single Flask process holding all state in memory (see db.py). Nothing is
seeded: every row is created by a client through a declared endpoint.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import base_meta, error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register_blueprints(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "No such route on this service.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this route.", 405
            )
        if exc.code in (400, 415, 422):
            return error_response(
                "ERR_INVALID_REQUEST",
                "The request body is malformed or violates a field constraint.",
                400,
            )
        payload = {
            "meta": base_meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": exc.description or "Request could not be processed.",
            },
        }
        return jsonify(payload), exc.code or 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        if isinstance(exc, HTTPException):
            return handle_http_error(exc)
        payload = {
            "meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(exc)},
        }
        return jsonify(payload), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
