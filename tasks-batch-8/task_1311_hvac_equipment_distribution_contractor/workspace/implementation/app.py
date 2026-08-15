"""HVAC Equipment Distribution & Contractor Program API.

Flask entry point. In-memory storage only; the store starts empty on every
boot. All time-dependent logic reads a server-maintained logical clock.
"""
import os

from flask import Flask, request

from errors import ApiError, ERR_NOT_FOUND
from response import error
from services.core import run_lazy_sweeps

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.clock_route import bp as clock_bp
from routes.contractors import bp as contractors_bp
from routes.catalog import bp as catalog_bp
from routes.programs import bp as programs_bp
from routes.orders import bp as orders_bp
from routes.warranty import bp as warranty_bp
from routes.refrigerant import bp as refrigerant_bp
from routes.rebates import bp as rebates_bp
from routes.training import bp as training_bp
from routes.coop import bp as coop_bp

PREFIX = "/api/v1"
for bp in (clock_bp, contractors_bp, catalog_bp, programs_bp, orders_bp,
           warranty_bp, refrigerant_bp, rebates_bp, training_bp, coop_bp):
    app.register_blueprint(bp, url_prefix=PREFIX)


@app.before_request
def lazy_sweeps():
    # Sweeps run on every read and every transition — but never on the
    # clock-setting call itself.
    if request.path == PREFIX + "/_clock/set_current_utc":
        return None
    run_lazy_sweeps()
    return None


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(exc):
    return error(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(500)
def handle_500(exc):
    return error("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
