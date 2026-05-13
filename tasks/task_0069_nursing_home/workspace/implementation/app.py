"""Nursing Home API entrypoint."""
import os
import traceback

from flask import Flask, jsonify

from errors import APIError
from response import error as error_response

# Route module imports register their @app.route handlers via register() calls.
from routes import (
    elders as elders_routes,
    rooms_beds as rooms_beds_routes,
    waitlist as waitlist_routes,
    care_assessments as care_assessments_routes,
    care_plans as care_plans_routes,
    prescriptions as prescriptions_routes,
    medication_errors as medication_errors_routes,
    visits as visits_routes,
    epidemic as epidemic_routes,
    bills as bills_routes,
    audit_logs as audit_logs_routes,
    ops as ops_routes,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register all blueprints
    elders_routes.register(app)
    rooms_beds_routes.register(app)
    waitlist_routes.register(app)
    care_assessments_routes.register(app)
    care_plans_routes.register(app)
    prescriptions_routes.register(app)
    medication_errors_routes.register(app)
    visits_routes.register(app)
    epidemic_routes.register(app)
    bills_routes.register(app)
    audit_logs_routes.register(app)
    ops_routes.register(app)

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "Bad request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"Unhandled: {e}", 500)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    # Run with threaded=False so RLock + dict ops execute sequentially for race tests.
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
