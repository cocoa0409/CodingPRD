"""Aircraft Parts AOG Desk API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from util import success, error_response

app = Flask(__name__)
app.json.sort_keys = False

from routes import customers, catalog, requests, quotes, orders, shipments, \
    core_returns, loans, warranty, rmas, system

for mod in (customers, catalog, requests, quotes, orders, shipments,
            core_returns, loans, warranty, rmas, system):
    app.register_blueprint(mod.bp)


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _not_found(_):
    err = ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return error_response(err)


@app.errorhandler(405)
def _method_not_allowed(_):
    err = ApiError(ERR_INVALID_REQUEST, 405, "Method not allowed")
    return error_response(err)


@app.errorhandler(Exception)
def _unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    wrapped = ApiError(ERR_INVALID_REQUEST, 500, f"Internal error: {err}")
    return error_response(wrapped)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
