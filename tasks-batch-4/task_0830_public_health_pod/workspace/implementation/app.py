import os
import traceback

from flask import Flask

from errors import ApiError
from response import error_response

from routes.hazard_plans import bp as hazard_plans_bp
from routes.pods import bp as pods_bp
from routes.staff_members import bp as staff_members_bp
from routes.shift_assignments import bp as shift_assignments_bp
from routes.countermeasures import bp as countermeasures_bp
from routes.inventory_lots import bp as inventory_lots_bp
from routes.allocation_requests import bp as allocation_requests_bp
from routes.dispensing_events import bp as dispensing_events_bp
from routes.drills import bp as drills_bp
from routes.situation_reports import bp as situation_reports_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(hazard_plans_bp)
    app.register_blueprint(pods_bp)
    app.register_blueprint(staff_members_bp)
    app.register_blueprint(shift_assignments_bp)
    app.register_blueprint(countermeasures_bp)
    app.register_blueprint(inventory_lots_bp)
    app.register_blueprint(allocation_requests_bp)
    app.register_blueprint(dispensing_events_bp)
    app.register_blueprint(drills_bp)
    app.register_blueprint(situation_reports_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_VALIDATION", "Resource or route not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_VALIDATION", "Method not allowed on this route.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected_error(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"Unexpected server error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
