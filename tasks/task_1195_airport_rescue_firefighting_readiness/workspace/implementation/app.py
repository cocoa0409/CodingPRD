"""ARFF Readiness API — entry point, error handlers, route registration."""
import os

from flask import Flask, request

from errors import ApiError
from middleware import authenticate
import response
from services.calc import apply_time_derived

from routes.profile import bp as profile_bp
from routes.aircraft import bp as aircraft_bp
from routes.fleet import bp as fleet_bp
from routes.roster import bp as roster_bp
from routes.drills import bp as drills_bp
from routes.determinations import bp as determinations_bp
from routes.incidents import bp as incidents_bp
from routes.mutual_aid import bp as mutual_aid_bp
from routes.notifications import bp as notifications_bp
from routes.reports import bp as reports_bp
from routes.inspections import bp as inspections_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _before():
        if request.path.startswith("/arff"):
            authenticate()
            apply_time_derived()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return response.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _internal(e):
        return response.error("ERR_INTERNAL", str(e), 500)

    for bp in (profile_bp, aircraft_bp, fleet_bp, roster_bp, drills_bp,
               determinations_bp, incidents_bp, mutual_aid_bp, notifications_bp,
               reports_bp, inspections_bp):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
