"""Entry point: error handlers + blueprint registration. In-memory only."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.operators import bp as operators_bp
from routes.aircraft import bp as aircraft_bp
from routes.fuel_contracts import bp as fuel_contracts_bp
from routes.service_visits import bp as service_visits_bp
from routes.parking_spots import bp as parking_spots_bp
from routes.parking_assignments import bp as parking_assignments_bp
from routes.fuel_orders import bp as fuel_orders_bp
from routes.into_plane_tickets import bp as into_plane_tickets_bp
from routes.ramp_services import bp as ramp_services_bp
from routes.ramp_slots import bp as ramp_slots_bp
from routes.invoices import bp as invoices_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        operators_bp, aircraft_bp, fuel_contracts_bp, service_visits_bp,
        parking_spots_bp, parking_assignments_bp, fuel_orders_bp,
        into_plane_tickets_bp, ramp_services_bp, ramp_slots_bp,
        invoices_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_MISSING_FIELD", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % exc, 422)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress (production WSGI server) — under the per-test-server
    # isolation sweep, many servers restart concurrently and the Werkzeug dev
    # server's tiny listen backlog drops SYNs, surfacing as ConnectTimeout.
    # waitress keeps a large connection backlog and accepts robustly under load.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, backlog=1024,
              connection_limit=1000, channel_timeout=120)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
