"""Ad Agency Ops API — entry point.

The in-memory store starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_INVALID_REQUEST", "No such route.", 404)
        if exc.code == 405:
            return response.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code and 400 <= exc.code < 500:
            return response.error("ERR_INVALID_REQUEST", exc.description or "Bad request.", 400)
        return response.error("ERR_INVALID_REQUEST", exc.description or "Error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("Unhandled error")
        return response.error("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
