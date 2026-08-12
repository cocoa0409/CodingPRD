"""Craft Cidery API — Flask entry point."""

import logging
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response

import routes_cellar
import routes_clock
import routes_compliance
import routes_orchard
import routes_packaging
import routes_sales

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    routes_clock,
    routes_orchard,
    routes_cellar,
    routes_compliance,
    routes_packaging,
    routes_sales,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, "resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, "method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", str(err), 500)


if __name__ == "__main__":
    # Suppress per-request access logging: under the per-test-server sweep the
    # process is rebooted hundreds of times and log formatting is pure CPU
    # overhead (output is discarded), which adds boot-window contention.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
