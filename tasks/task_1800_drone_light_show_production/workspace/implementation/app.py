"""Drone Light Show Production API — Flask entry point."""

import os
import traceback

from flask import Flask

import errors
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.sites import bp as sites_bp
    from routes.shows import bp as shows_bp
    from routes.authorizations import bp as auth_bp
    from routes.designs import bp as designs_bp
    from routes.simulations import bp as sims_bp
    from routes.safety import bp as safety_bp
    from routes.drones import bp as drones_bp
    from routes.charging import bp as charging_bp
    from routes.assignments import bp as assignments_bp
    from routes.weather import bp as weather_bp
    from routes.evaluations import bp as evals_bp
    from routes.incidents import bp as incidents_bp
    from routes.flight_logs import bp as flight_logs_bp
    from routes.ops import bp as ops_bp

    for bp in (sites_bp, shows_bp, auth_bp, designs_bp, sims_bp, safety_bp,
               drones_bp, charging_bp, assignments_bp, weather_bp, evals_bp,
               incidents_bp, flight_logs_bp, ops_bp):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
