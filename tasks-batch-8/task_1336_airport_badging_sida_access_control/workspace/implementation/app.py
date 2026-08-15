"""Airport Badging & SIDA Access Control API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_payload


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    from routes import (
        access,
        applicants,
        applications,
        audit,
        badges,
        clock,
        escort,
        sponsors,
        training,
        violations,
    )

    for module in (
        sponsors,
        applicants,
        applications,
        training,
        badges,
        escort,
        access,
        violations,
        audit,
        clock,
    ):
        app.register_blueprint(module.bp, url_prefix="/badging")

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return jsonify(error_payload(err.error_id, err.message)), err.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        status = err.code or 500
        error_id = "ERR_NOT_FOUND" if status == 404 else "ERR_INVALID_REQUEST"
        return jsonify(error_payload(error_id, err.description)), status

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return (
            jsonify(error_payload("ERR_INTERNAL", "Internal server error")),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
