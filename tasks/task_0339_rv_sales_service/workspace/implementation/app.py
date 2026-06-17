"""RV Sales & Service API — entry point, error handlers, route registration."""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        body = error_body("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        body = error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        body = error_body("ERR_INVALID_REQUEST", "Malformed request.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = error_body("ERR_INTERNAL", str(exc))
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
