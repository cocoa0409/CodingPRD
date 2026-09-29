"""Pavement Management & Resurfacing Program API.

All state lives in process memory (see db.py) and is empty on every boot:
nothing is seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (acceptance_tests, allocations, candidates, contractors,
                    coordinations, cut_permits, observations, project_segments,
                    projects, scenarios, segments, service_requests, surveys)

PREFIX = "/pavement"

BLUEPRINTS = (
    segments.bp,
    surveys.bp,
    observations.bp,
    candidates.bp,
    scenarios.bp,
    allocations.bp,
    contractors.bp,
    projects.bp,
    project_segments.bp,
    coordinations.bp,
    cut_permits.bp,
    acceptance_tests.bp,
    service_requests.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message,
                                       exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "This method is not allowed for the requested resource.", 405)
        if exc.code in (400, 415):
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request is malformed.", 400)
        return response.error_response(
            "ERR_INTERNAL", exc.description or "Unexpected error.",
            exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return response.error_response(
            "ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
