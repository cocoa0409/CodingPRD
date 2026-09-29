"""Farm and Ranch Package Underwriting API.

A single-process Flask service with in-memory storage only: the store is
empty on every boot and nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.core import bp as core_bp
from routes.losscontrol import bp as losscontrol_bp
from routes.reference import bp as reference_bp
from routes.underwriting import bp as underwriting_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(reference_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(underwriting_bp)
    app.register_blueprint(losscontrol_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed on this path.", 405
            )
        if exc.code and 400 <= exc.code < 500:
            return response.error("ERR_INVALID_REQUEST", exc.description or "Bad request.", 400)
        return response.error("ERR_INTERNAL", exc.description or "Internal error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
