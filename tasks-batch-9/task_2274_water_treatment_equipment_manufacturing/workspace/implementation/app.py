"""Water Treatment Equipment Manufacturing API (Flask, in-memory).

Boots empty on every invocation: no seeding, no persistence, no disk cache.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

PREFIX = "/water-treatment"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes import BLUEPRINTS
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error_body(
                "ERR_INVALID_REQUEST", "resource not found"), 404
        if exc.code == 405:
            return response.error_body(
                "ERR_INVALID_REQUEST", "method not allowed"), 405
        if exc.code in (400, 415):
            return response.error_body(
                "ERR_INVALID_REQUEST", exc.description or "invalid request"), 400
        return response.error_body(
            "ERR_INVALID_REQUEST", exc.description or "request failed"), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return response.error_body("ERR_INVALID_REQUEST", str(exc)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
