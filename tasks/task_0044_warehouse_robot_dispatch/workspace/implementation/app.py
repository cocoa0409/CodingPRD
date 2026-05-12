"""Warehouse Robot Dispatch API — Flask entry point."""

import os
import string
import random

from flask import Flask, request, g

from errors import APIError
from middleware import authenticate
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # --- Register blueprints ---
    from routes.fleets import fleets_bp
    from routes.map_and_events import map_bp
    from routes.charging_stations import charging_stations_bp
    from routes.robots import robots_bp
    from routes.tasks import tasks_bp
    from routes.slot_reservations import slots_bp
    from routes.fault_incidents import fault_bp
    from routes.audit_and_sessions import audit_bp

    app.register_blueprint(fleets_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(charging_stations_bp)
    app.register_blueprint(robots_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(fault_bp)
    app.register_blueprint(audit_bp)

    @app.before_request
    def _before_request():
        # Generate a request id; auth on every request
        alphabet = string.ascii_uppercase + string.digits
        g.request_id = "req_" + "".join(random.choices(alphabet, k=20))
        # Skip auth for nothing — every endpoint requires headers.
        authenticate()

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return error_response("ERR_BAD_REQUEST", "Method not allowed", 400)

    @app.errorhandler(400)
    def _bad_request(_e):
        return error_response("ERR_BAD_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def _unhandled(e):
        # For unexpected errors, return a 500 in our standard envelope.
        return error_response("ERR_BAD_REQUEST", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
