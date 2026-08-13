"""Entry point: app factory, error handlers, route registration.

The store starts EMPTY on every boot (db module-level dicts); nothing is
seeded. All state is built through the declared API surface.
"""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes import (labs, workers, containers, areas, pickups, inspections,
                    corrective_actions, training, incidents, registrations, clock)


def create_app():
    app = Flask(__name__)

    for module in (labs, workers, containers, areas, pickups, inspections,
                   corrective_actions, training, incidents, registrations, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response(ERR_INVALID_REQUEST, str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
