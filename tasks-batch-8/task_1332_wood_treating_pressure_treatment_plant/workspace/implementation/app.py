"""Wood Treating Plant API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error as error_response
from routes import (
    plants, cylinders, preservatives, customers, charges, charge_children,
    cycles, inspections, flat, admin,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_INVALID_REQUEST, "Route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ERR_INVALID_REQUEST, "Internal error: " + str(err), 500)

    for module in (
        plants, cylinders, preservatives, customers, charges, charge_children,
        cycles, inspections, flat, admin,
    ):
        app.register_blueprint(module.bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
