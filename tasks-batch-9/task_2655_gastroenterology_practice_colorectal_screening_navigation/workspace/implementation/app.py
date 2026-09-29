"""Flask application factory and process entry point.

Storage is in-memory only and starts completely empty on every boot; nothing is
seeded, preloaded or hardcoded.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
from routes import bookings, claims, episodes, pathology, quality
from routes import recommendations, reference, referrals, sessions, tests

_LOCK = threading.Lock()


class SerializingMiddleware(object):
    """Serialize requests so cascades are atomic against concurrent callers."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _LOCK:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        reference,
        referrals,
        episodes,
        tests,
        sessions,
        bookings,
        pathology,
        recommendations,
        claims,
        quality,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return respond_error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return respond_error(
            "ERR_INVALID_REQUEST", "The method is not allowed for this resource.", 405
        )

    @app.errorhandler(400)
    def handle_400(exc):
        return respond_error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return respond_error(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return respond_error(
                "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
            )
        return respond_error("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
