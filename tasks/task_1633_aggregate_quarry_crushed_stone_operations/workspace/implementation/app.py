"""Aggregate Quarry & Crushed-Stone Operations API — Flask entry point."""

import os

from flask import Flask

from core import error_body
from errors import ApiError, err_not_found, err_invalid_request
import routes_core
import routes_commerce


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_commerce.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        e = err_not_found("Route not found")
        return error_body(e.error_id, e.message), e.http_status

    @app.errorhandler(405)
    def handle_405(err):
        e = err_not_found("Route not found")
        return error_body(e.error_id, e.message), e.http_status

    @app.errorhandler(400)
    def handle_400(err):
        if isinstance(err, ApiError):
            return error_body(err.error_id, err.message), err.http_status
        e = err_invalid_request("Bad request")
        return error_body(e.error_id, e.message), e.http_status

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_body(err.error_id, err.message), err.http_status
        e = err_invalid_request(f"Unexpected error: {err}")
        return error_body(e.error_id, e.message), e.http_status

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
