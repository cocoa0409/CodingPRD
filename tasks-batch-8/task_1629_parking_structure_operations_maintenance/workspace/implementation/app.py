"""Parking Structure Operations & Maintenance API — Flask application entry point."""
import os
import traceback

from flask import Flask

from errors import ApiError
from response import error_response

from routes import (
    clock, facilities, rates, devices, parkers, agreements, credentials,
    sessions, shifts, reconciliations, inspections, repairs, windows,
    patrols, incidents, chargers, charging, events,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(facilities.bp)
    app.register_blueprint(rates.bp)
    app.register_blueprint(devices.bp)
    app.register_blueprint(parkers.bp)
    app.register_blueprint(agreements.bp)
    app.register_blueprint(credentials.bp)
    app.register_blueprint(sessions.bp)
    app.register_blueprint(shifts.bp)
    app.register_blueprint(reconciliations.bp)
    app.register_blueprint(inspections.bp)
    app.register_blueprint(repairs.bp)
    app.register_blueprint(windows.bp)
    app.register_blueprint(patrols.bp)
    app.register_blueprint(incidents.bp)
    app.register_blueprint(chargers.bp)
    app.register_blueprint(charging.bp)
    app.register_blueprint(events.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "route or resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_VALIDATION", 400, "malformed request")

    @app.errorhandler(Exception)
    def handle_exception(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, f"internal error: {err}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
