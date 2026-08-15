"""School Spirit Store & Merchandise Program — API entry point.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. All state is in
memory and starts empty on every boot.
"""
import os
import traceback

from flask import Flask, jsonify

from core import (ApiError, ERR_INVALID_REQUEST, error_response, new_ts,
                  req_id)
import routes_catalog
import routes_supply
import routes_sales
import routes_finance

app = Flask(__name__)
app.register_blueprint(routes_catalog.bp)
app.register_blueprint(routes_supply.bp)
app.register_blueprint(routes_sales.bp)
app.register_blueprint(routes_finance.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_INVALID_REQUEST, 404, "resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_INVALID_REQUEST, 405, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    return error_response(ERR_INVALID_REQUEST, 500,
                          "internal error: %s" % err)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
