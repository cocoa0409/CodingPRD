"""Flask entry point for the School Volunteer Screening & Placement API."""

import os
from flask import Flask, jsonify

from errors import APIError
from response import error_response
import clock

import routes.campuses
import routes.volunteers
import routes.background_checks
import routes.training
import routes.opportunities
import routes.placements
import routes.hour_entries
import routes.check_ins
import routes.incidents
import routes.awards
import routes.clock_routes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Fresh boot: reset logical clock to startup default
    clock.reset()

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_generic(err):
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    for mod in (
        routes.campuses,
        routes.volunteers,
        routes.background_checks,
        routes.training,
        routes.opportunities,
        routes.placements,
        routes.hour_entries,
        routes.check_ins,
        routes.incidents,
        routes.awards,
        routes.clock_routes,
    ):
        mod.register(app)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
