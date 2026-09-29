"""Newborn Hearing Screening & Follow-Up Tracking API.

In-memory only: every collection lives in a Python dict that is empty on boot.
Nothing is seeded, preloaded or persisted, and the logical clock always starts
at exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in routes.BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_envelope(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error_envelope(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error_envelope(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return handle_not_found(exc)
        if exc.code == 405:
            return handle_method_not_allowed(exc)
        if exc.code == 400:
            return response.error_envelope(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return response.error_envelope(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error_envelope("ERR_INTERNAL", str(exc) or "Unexpected error.",
                                       500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
