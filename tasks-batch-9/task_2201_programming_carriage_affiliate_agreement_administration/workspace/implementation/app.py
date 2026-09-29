"""Carriage Affiliate Agreement Administration API.

In-memory only: every process starts with completely empty tables and the
logical clock pinned to 2026-08-01T00:00:00Z.  Nothing is seeded, persisted or
read back from disk.
"""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import respond_error
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return respond_error(
                "ERR_METHOD_NOT_ALLOWED", "method not allowed for this route", 405
            )
        if exc.code == 400:
            return respond_error("ERR_INVALID_REQUEST", "malformed request", 400)
        return respond_error(
            "ERR_INTERNAL", exc.description or "request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        traceback.print_exc()
        return respond_error("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
