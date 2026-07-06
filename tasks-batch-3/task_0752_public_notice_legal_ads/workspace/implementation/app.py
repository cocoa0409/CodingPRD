"""Entry point: builds the Flask app, wires error handling to the standard
envelope, and runs the server in the foreground on 0.0.0.0:$PORT.

State is entirely in-memory and starts empty on every boot (see store.py); no
entity is ever seeded.
"""
import os

from flask import Flask, jsonify

from core import ApiError, error_body
from routes import register


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def _handle_404(_e):
        return error_body(ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(405)
    def _handle_405(_e):
        return error_body(ApiError("ERR_NOT_FOUND", 404, "method not allowed"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_body(err)
        body = {
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
