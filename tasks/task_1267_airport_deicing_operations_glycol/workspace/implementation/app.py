"""Flask app entry point: registers blueprints and error handlers.

The store starts empty on every boot — nothing is seeded here.
"""
import os

from flask import Flask

import errors as err
import response
from routes import (
    airlines,
    clock,
    deice_operations,
    deice_requests,
    discharge_permits,
    fluid_tanks,
    inspections,
    invoices,
    pads,
    recycling_contracts,
    spill_reports,
    stations,
    weather_events,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(stations.bp)
    app.register_blueprint(pads.bp)
    app.register_blueprint(weather_events.bp)
    app.register_blueprint(fluid_tanks.bp)
    app.register_blueprint(airlines.bp)
    app.register_blueprint(deice_requests.bp)
    app.register_blueprint(deice_operations.bp)
    app.register_blueprint(inspections.bp)
    app.register_blueprint(discharge_permits.bp)
    app.register_blueprint(spill_reports.bp)
    app.register_blueprint(recycling_contracts.bp)
    app.register_blueprint(invoices.bp)
    app.register_blueprint(clock.bp)

    @app.errorhandler(err.ApiError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error_response(err.ERR_NOT_FOUND, 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return response.error_response(err.ERR_NOT_FOUND, 404, "method not allowed on this path")

    @app.errorhandler(400)
    def handle_400(e):
        return response.error_response(err.ERR_INVALID_REQUEST, 400, "malformed request")

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, err.ApiError):
            return response.error_response(e.error_id, e.http_status, e.message)
        # Unexpected error: surface as 500 with a generic envelope.
        return response.error_response("ERR_INTERNAL", 500, str(e)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
