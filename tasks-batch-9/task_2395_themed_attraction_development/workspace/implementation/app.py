"""Themed Attraction Development Coordination Service -- Flask application.

State lives entirely in process memory (see store.py); every boot starts empty
and the logical clock starts at exactly 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g

import response
from errors import ApiError
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_all(app)

    @app.before_request
    def _begin_request():
        # A resource's version counter advances at most once per request.
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return response.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", 405)

    @app.errorhandler(415)
    def _unsupported_media(exc):
        return response.error("ERR_INVALID_REQUEST", "Unsupported media type.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):  # pragma: no cover - defensive
            return response.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
