"""Transmission Line Routing & Siting Certificate API (task 2334).

Flask application factory and error handling. All state lives in process memory
(see db.py); every boot starts from an empty store with the logical clock at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response as resp
from errors import ERROR_CATALOG, ApiError
from routes import (
    admin,
    certificates,
    comments,
    construction,
    corridors,
    docket,
    easements,
    projects,
    studies,
)

BLUEPRINTS = (
    projects.bp,
    studies.bp,
    corridors.bp,
    comments.bp,
    docket.bp,
    certificates.bp,
    easements.bp,
    construction.bp,
    admin.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(resp.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            error_id = "ERR_RESOURCE_NOT_FOUND"
            message = "No such resource."
        elif exc.code == 405:
            error_id = "ERR_INVALID_REQUEST"
            message = "The HTTP method is not allowed for this path."
        elif exc.code == 401:
            error_id = "ERR_UNAUTHENTICATED"
            message = "Authentication headers missing or empty."
        elif exc.code == 403:
            error_id = "ERR_UNAUTHORIZED"
            message = "Not permitted."
        elif exc.code and exc.code >= 500:
            error_id = "ERR_INTERNAL"
            message = "Internal server error."
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = exc.description or "Malformed request."
        status = ERROR_CATALOG.get(error_id, exc.code or 400)
        return jsonify(resp.error_body(error_id, message)), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return jsonify(resp.error_body("ERR_INTERNAL", "Internal server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
