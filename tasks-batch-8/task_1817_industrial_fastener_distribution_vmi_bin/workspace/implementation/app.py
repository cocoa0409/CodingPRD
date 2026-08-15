"""VMI bin programme API — Flask entry point."""

import os

from flask import Flask

import errors
from response import error
from routes import (
    system, sites, parts, xrefs, agreements, routes_mod, orders, certs, kits,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    system.bp,
    sites.bp,
    parts.bp,
    xrefs.bp,
    agreements.bp,
    routes_mod.bp,
    orders.bp,
    certs.bp,
    kits.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_e):
    return error(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_e):
    return error(errors.ERR_NOT_FOUND, "Resource not found", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Never leak a bare 500 HTML page through the envelope contract.
    return error(errors.ERR_INVALID_REQUEST, "Unhandled server error: %s" % exc, 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
