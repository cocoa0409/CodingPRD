"""Trademark Watch & Enforcement API — Flask entry point.

The store is in-memory only and starts completely empty on every boot; the
harness restarts this process before every test (per-test-server isolation).
"""

import os

from flask import Flask

from errors import ApiError, ERR_VALIDATION, ERR_NOT_FOUND
from response import error as error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_VALIDATION, 400, "Malformed request")

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
