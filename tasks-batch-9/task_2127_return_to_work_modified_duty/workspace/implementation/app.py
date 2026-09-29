"""Return-To-Work & Modified Duty Program API.

Storage is entirely in-memory and starts empty on every boot; no entity is
seeded, preloaded or hardcoded here or anywhere else in the process.
"""
import os
import threading

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body

import api_core
import api_placement
import api_review


class SerializingMiddleware:
    """Serialise request handling so every multi-record cascade is atomic."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.RLock()

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(api_core.bp)
    app.register_blueprint(api_placement.bp)
    app.register_blueprint(api_review.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body(
                "ERR_INVALID_REQUEST", "No such route.")), 404
        if exc.code == 405:
            return jsonify(error_body(
                "ERR_INVALID_REQUEST", "Method not allowed.")), 405
        return jsonify(error_body(
            "ERR_INVALID_REQUEST", exc.description or "Bad request")), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 400

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
