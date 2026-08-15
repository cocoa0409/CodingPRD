"""Builder Warranty API — entry point, error handlers, route registration.

In-memory only: the store lives in module-level dicts and starts empty on every
process boot (prd-bench-local-run --isolation per-test-server re-launches
start.sh before every test, which wipes all state).
"""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(ERR_INVALID_REQUEST[0], "route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(ERR_INVALID_REQUEST[0], "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(ERR_INVALID_REQUEST[0], str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
