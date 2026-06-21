"""Cold-Chain & Reefer Logistics API — Flask entry point.

In-memory storage only; no seeding at startup (the store is created empty in
db.py and every entity is built via the declared API surface). Boots cleanly
from a fresh process on every invocation.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.carriers import bp as carriers_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp
from routes.compartments import bp as compartments_bp
from routes.product_lots import bp as product_lots_bp
from routes.readings import bp as readings_bp
from routes.reefer_units import bp as reefer_units_bp
from routes.shipments import bp as shipments_bp
from routes.stops import bp as stops_bp
from routes.temp_lanes import bp as temp_lanes_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(carriers_bp)
    app.register_blueprint(reefer_units_bp)
    app.register_blueprint(temp_lanes_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(compartments_bp)
    app.register_blueprint(readings_bp)
    app.register_blueprint(product_lots_bp)
    app.register_blueprint(stops_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(_exc):
        # Method not allowed on a known path -> treat as not found per the
        # framework's not-found contract.
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
