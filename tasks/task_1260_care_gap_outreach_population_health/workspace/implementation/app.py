"""Entry point: Flask app assembly, error handlers, route registration."""

import os

from flask import Flask

import errors as E
import util as U
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return U.error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return U.error_response(
            ApiError(E.ERR_NOT_FOUND, "The requested resource was not found", 404)
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return U.error_response(
            ApiError(E.ERR_NOT_FOUND, "The requested resource was not found", 404)
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return U.error_response(
            ApiError(E.ERR_INVALID_REQUEST, f"Unexpected error: {err}", 400)
        )

    import routes_registry
    import routes_outreach
    import routes_review

    routes_registry.register_routes(app)
    routes_outreach.register_routes(app)
    routes_review.register_routes(app)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
