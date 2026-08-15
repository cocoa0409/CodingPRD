"""Streetlight LED Conversion API — Flask entry point.

In-memory only: every process boot starts with a completely empty store; all
state is constructed by clients through the declared API surface.
"""
import os
import traceback

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes import ALL_BLUEPRINTS


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "resource or route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"internal error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
