"""Domestic-violence shelter safety-planning API.

Flask application factory and error plumbing.  All state lives in the
process-local in-memory store of db.py; nothing is seeded at startup and
nothing is persisted to disk, so every boot starts from an empty system.
"""

import os

from flask import Flask, jsonify

from errors import DEFAULT_MESSAGES, ERROR_STATUS, ApiError
from response import error_body
from routes import (admissions, clients, clock, disclosure, hotline, housing, plans,
                    protective, screening, shelters, staff)

BLUEPRINTS = (
    staff.bp,
    clients.bp,
    hotline.bp,
    plans.bp,
    shelters.bp,
    screening.bp,
    admissions.bp,
    protective.bp,
    housing.bp,
    disclosure.bp,
    clock.bp,
)


def _error_response(error_id, message=None, status=None):
    body = error_body(error_id, message or DEFAULT_MESSAGES.get(error_id, error_id))
    return jsonify(body), status or ERROR_STATUS.get(error_id, 500)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return _error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_400(exc):
        return _error_response("ERR_INVALID_REQUEST", "malformed request")

    @app.errorhandler(404)
    def handle_404(exc):
        return _error_response("ERR_NOT_FOUND", "no such route", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return _error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(415)
    def handle_415(exc):
        return _error_response("ERR_INVALID_REQUEST", "unsupported media type")

    @app.errorhandler(422)
    def handle_422(exc):
        return _error_response("ERR_INVALID_REQUEST", "unprocessable request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return _error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return _error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
