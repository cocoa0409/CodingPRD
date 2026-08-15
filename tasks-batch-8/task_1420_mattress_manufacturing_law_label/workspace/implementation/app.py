"""Entry point: Flask app, error handlers, route registration."""
import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import errors
import response
from routes import (
    bom_lines,
    certificates,
    clock_route,
    foam_batches,
    law_labels,
    models,
    orders,
    quilt_runs,
    recycling,
    retailers,
    returns,
    shipments,
    specs,
    units,
    warranty,
)

app = Flask(__name__)

PREFIX = "/plant"

for bp in (
    clock_route.bp,
    retailers.bp,
    models.bp,
    bom_lines.bp,
    certificates.bp,
    specs.bp,
    law_labels.bp,
    foam_batches.bp,
    quilt_runs.bp,
    orders.bp,
    units.bp,
    shipments.bp,
    returns.bp,
    warranty.bp,
    recycling.bp,
):
    app.register_blueprint(bp, url_prefix=PREFIX)


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return response.error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return response.error_response(
        errors.ApiError("ERR_NOT_FOUND", 404, "route not found")
    )


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return response.error_response(
        errors.ApiError("ERR_NOT_FOUND", 404, "route not found")
    )


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return response.error_response(err)
    return response.error_response(
        errors.ApiError("ERR_INTERNAL", 500, "internal error: %s" % err)
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
