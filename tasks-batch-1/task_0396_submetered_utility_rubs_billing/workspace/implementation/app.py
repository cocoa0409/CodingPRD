"""Entry point: app factory, error handlers, blueprint registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.clock import clock_bp
from routes.properties import properties_bp
from routes.utilities import utilities_bp
from routes.units import units_bp
from routes.meters import meters_bp
from routes.leases import leases_bp
from routes.vendor_bills import vendor_bills_bp
from routes.meter_reads import meter_reads_bp
from routes.billing_cycles import billing_cycles_bp
from routes.statements import statements_bp
from routes.payments import payments_bp
from routes.disputes import disputes_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, properties_bp, utilities_bp, units_bp, meters_bp,
        leases_bp, vendor_bills_bp, meter_reads_bp, billing_cycles_bp,
        statements_bp, payments_bp, disputes_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
