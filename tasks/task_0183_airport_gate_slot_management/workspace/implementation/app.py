"""Airport Gate & Slot Management API — Flask entry point.

In-memory only. Store starts EMPTY on every boot (no seeding). Re-launching via
start.sh produces a fresh process with a pristine store.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

# Route blueprints
from routes.gates import bp as gates_bp
from routes.remote_stands import bp as remote_stands_bp
from routes.cute_units import bp as cute_units_bp
from routes.ground_equipment import bp as ground_equipment_bp
from routes.flights import bp as flights_bp
from routes.gate_assignments import bp as gate_assignments_bp
from routes.slot_permits import bp as slot_permits_bp
from routes.cute_allocations import bp as cute_allocations_bp
from routes.gse_allocations import bp as gse_allocations_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(gates_bp)
    app.register_blueprint(remote_stands_bp)
    app.register_blueprint(cute_units_bp)
    app.register_blueprint(ground_equipment_bp)
    app.register_blueprint(flights_bp)
    app.register_blueprint(gate_assignments_bp)
    app.register_blueprint(slot_permits_bp)
    app.register_blueprint(cute_allocations_bp)
    app.register_blueprint(gse_allocations_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        # Unknown route / path -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface unexpected errors as a generic 500 in the standard envelope.
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
