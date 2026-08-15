"""Substation Maintenance & Testing Services API — Flask application entry point."""
import os
import traceback

from flask import Flask

from errors import ApiError
from response import error_response

from routes import (
    clock, substations, asset_class_policies, assets, outage_windows,
    switching_steps, test_events, defects, work_orders, spare_units,
    spare_reservations, relay_settings, technicians, environmental_inspections,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    app.register_blueprint(clock.bp)
    app.register_blueprint(substations.bp)
    app.register_blueprint(asset_class_policies.bp)
    app.register_blueprint(assets.bp)
    app.register_blueprint(outage_windows.bp)
    app.register_blueprint(switching_steps.bp)
    app.register_blueprint(test_events.bp)
    app.register_blueprint(defects.bp)
    app.register_blueprint(work_orders.bp)
    app.register_blueprint(spare_units.bp)
    app.register_blueprint(spare_reservations.bp)
    app.register_blueprint(relay_settings.bp)
    app.register_blueprint(technicians.bp)
    app.register_blueprint(environmental_inspections.bp)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

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
        return error_response("ERR_VALIDATION", 500, f"internal error: {err}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
