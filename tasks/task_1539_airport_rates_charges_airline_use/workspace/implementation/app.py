"""Airport Rates & Charges API — Flask entry point.

In-memory store, logical clock, no seeding. Boots clean from a fresh process
on every invocation (per-test-server isolation).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
import errors as err
import routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err.not_found("Path does not resolve"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err.not_found("Method not allowed on this path"))

    @app.errorhandler(500)
    def handle_500(e):
        return error_response(err.invalid_request("Internal server error"))

    routes.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
