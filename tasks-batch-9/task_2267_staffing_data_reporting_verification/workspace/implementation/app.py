"""Staffing Data Reporting & Verification API — Flask application entry point.

State lives entirely in process memory (see db.py) and starts empty on every
boot; nothing is seeded, persisted, or cached on disk.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_NOT_FOUND", "The requested resource does not exist.")), 404
        if exc.code == 405:
            return (
                jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.")),
                405,
            )
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "The request could not be processed.")),
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return (
            jsonify(error_body("ERR_INTERNAL", "Unexpected server error: %s" % exc)),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
