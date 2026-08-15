"""Entry point: Flask app, error handlers, route registration. No seeding at startup."""
import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import (
    clock, customers, cut_programs, drop_tests, inventory_programs, materials,
    package_specs, production_orders, release_orders, scrap_batches, toolings,
)

for module in (
    clock, customers, materials, package_specs, cut_programs, toolings,
    drop_tests, production_orders, inventory_programs, release_orders,
    scrap_batches,
):
    app.register_blueprint(module.bp, url_prefix="/api")


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response(errors.ERR_INVALID_REQUEST, f"Internal error: {exc}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
