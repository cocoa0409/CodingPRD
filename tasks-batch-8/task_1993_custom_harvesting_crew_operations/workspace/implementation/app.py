"""Custom Harvesting Crew Operations API — entry point.

Mounts all route blueprints under /harvest, registers error handlers for
the standard error envelope, and binds 0.0.0.0:$PORT (default 10000).
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response, success_object

from routes.seasons import bp as seasons_bp
from routes.contracts import bp as contracts_bp
from routes.route_stops import bp as route_stops_bp
from routes.machines import bp as machines_bp
from routes.crew import bp as crew_bp
from routes.machine_assignments import bp as assignments_bp
from routes.delivery_tickets import bp as tickets_bp
from routes.settlements import bp as settlements_bp
from routes.lodging import bp as lodging_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        seasons_bp,
        contracts_bp,
        route_stops_bp,
        machines_bp,
        crew_bp,
        assignments_bp,
        tickets_bp,
        settlements_bp,
        lodging_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        # A URL matching no declared route is a generic request-shape error.
        return error_response(
            ApiError(ERR_INVALID_REQUEST, 400, "Unknown route or malformed request")
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(
            ApiError(ERR_INVALID_REQUEST, 400, "Method not allowed for this route")
        )

    @app.errorhandler(500)
    def handle_internal_error(err):
        return error_response(
            ApiError(ERR_INVALID_REQUEST, 400, "Internal request processing error")
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
