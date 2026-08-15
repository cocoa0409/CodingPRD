"""Flask entry point: app factory, error handlers, blueprint registration."""

import os

from flask import Flask

from httpkit import ApiError, respond_error

import routes_assignments
import routes_ops
import routes_registry
import routes_trips


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_registry, routes_trips, routes_assignments,
                   routes_ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return respond_error(err)

    @app.errorhandler(404)
    def handle_404(err):
        return respond_error(ApiError(
            "ERR_INVALID_REQUEST", 400, "The requested path does not exist"))

    @app.errorhandler(405)
    def handle_405(err):
        return respond_error(ApiError(
            "ERR_INVALID_REQUEST", 400, "The requested path does not exist"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return respond_error(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
