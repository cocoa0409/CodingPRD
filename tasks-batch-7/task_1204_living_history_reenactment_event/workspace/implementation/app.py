"""Flask entry point: error handlers, route registration, server bootstrap."""

import os

from flask import Flask

from errors import ApiError
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        agreements,
        alerts,
        areas,
        clock,
        equipment,
        events,
        participants,
        slots,
        tickets,
        units,
        vendors,
    )

    for module in (
        events,
        agreements,
        units,
        participants,
        equipment,
        areas,
        slots,
        tickets,
        vendors,
        alerts,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_):
        return error("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_):
        return error("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
