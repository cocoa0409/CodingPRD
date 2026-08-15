"""Cardiac Cath Lab API — entry point, error handlers, route registration."""
import os
import traceback

from flask import Flask

from errors import (
    ApiError,
    ERR_INTERNAL,
    ERR_METHOD_NOT_ALLOWED,
    ERR_NOT_FOUND,
)
from response import error
from routes import (
    assignments,
    beds,
    cases,
    clock,
    devices,
    doses,
    registry,
    rooms,
    staff,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(rooms.bp)
    app.register_blueprint(staff.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(assignments.bp)
    app.register_blueprint(devices.bp)
    app.register_blueprint(doses.bp)
    app.register_blueprint(beds.bp)
    app.register_blueprint(registry.bp)
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error(err)

    @app.errorhandler(404)
    def handle_not_found(_):
        return error(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_method_not_allowed(_):
        return error(ApiError(ERR_METHOD_NOT_ALLOWED, "Method not allowed", 405))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error(ApiError(ERR_INTERNAL, "Internal server error", 500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
