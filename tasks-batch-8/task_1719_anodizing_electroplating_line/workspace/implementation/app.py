"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    from routes import (
        baths,
        clock,
        compat_rules,
        customers,
        fixtures,
        load_runs,
        manifests,
        permits,
        salt_spray,
        work_orders,
    )

    for module in (
        customers,
        fixtures,
        compat_rules,
        baths,
        work_orders,
        load_runs,
        salt_spray,
        permits,
        manifests,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        error_id, status = ERR_NOT_FOUND
        return error_response(error_id, status, "resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        error_id, status = ERR_NOT_FOUND
        return error_response(error_id, 404, "resource not found")

    @app.errorhandler(400)
    def handle_400(err):
        error_id, status = ERR_INVALID_REQUEST
        return error_response(error_id, status, "malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        error_id, status = ERR_INVALID_REQUEST
        return error_response(error_id, status, "unexpected error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
