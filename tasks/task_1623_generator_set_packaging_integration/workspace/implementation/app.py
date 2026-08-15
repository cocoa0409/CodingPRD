"""Entry point for the genset-packaging REST API.

Mounts all route blueprints, registers the error handler, and starts Flask
on $PORT (default 10000) bound to 0.0.0.0 in the foreground.
"""

import os

from flask import Flask

import errors
import response as resp
from routes.clock import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.catalogs import bp as catalogs_bp
from routes.orders import bp as orders_bp
from routes.sizing_studies import bp as sizing_studies_bp
from routes.configurations import bp as configurations_bp
from routes.permits import bp as permits_bp
from routes.emissions import bp as emissions_bp
from routes.paralleling import bp as paralleling_bp
from routes.test_bays import bp as test_bays_bp
from routes.factory_tests import bp as factory_tests_bp
from routes.crane_slots import bp as crane_slots_bp
from routes.shipments import bp as shipments_bp
from routes.commissioning import bp as commissioning_bp
from routes.service_contracts import bp as service_contracts_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

# Register all blueprints
for bp in (
    clock_bp,
    customers_bp,
    catalogs_bp,
    orders_bp,
    sizing_studies_bp,
    configurations_bp,
    permits_bp,
    emissions_bp,
    paralleling_bp,
    test_bays_bp,
    factory_tests_bp,
    crane_slots_bp,
    shipments_bp,
    commissioning_bp,
    service_contracts_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return resp.error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return resp.error_response(errors.not_found("Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return resp.error_response(
        errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "Method not allowed")
    )


@app.errorhandler(500)
def handle_internal_error(err):
    return resp.error_response(
        errors.ApiError(errors.ERR_INVALID_REQUEST, 400, str(err))
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
