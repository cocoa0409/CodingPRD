"""Airport Ground-Transport & TNC Permitting API — Flask entry point.

In-memory store only; state is wiped on every process launch. Nothing is seeded.
"""
import os

from flask import Flask, jsonify

from common import error_response
from errors import ApiError

from routes.clock import bp as clock_bp
from routes.operators import bp as operators_bp
from routes.vehicles import bp as vehicles_bp
from routes.permits import bp as permits_bp
from routes.staging_lots import bp as staging_lots_bp
from routes.queue_entries import bp as queue_entries_bp
from routes.curb_zones import bp as curb_zones_bp
from routes.curb_assignments import bp as curb_assignments_bp
from routes.trips import bp as trips_bp
from routes.violations import bp as violations_bp
from routes.settlements import bp as settlements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        operators_bp,
        vehicles_bp,
        permits_bp,
        staging_lots_bp,
        queue_entries_bp,
        curb_zones_bp,
        curb_assignments_bp,
        trips_bp,
        violations_bp,
        settlements_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return jsonify({
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
