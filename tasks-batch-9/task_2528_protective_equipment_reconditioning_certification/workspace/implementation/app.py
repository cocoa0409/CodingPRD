"""Protective Equipment Reconditioning API — application entry point.

The store is in-memory and starts completely empty on every boot: nothing is
seeded, preloaded or hardcoded. Every entity is created through the API.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
import routes_accounts
import routes_labels
import routes_loaners
import routes_reference
import routes_repairs
import routes_shipments
import routes_tests
import routes_units
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (routes_reference, routes_accounts, routes_shipments, routes_units,
               routes_tests, routes_repairs, routes_labels, routes_loaners):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error_response(exc)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        error_id, message = "ERR_NOT_FOUND", "No such route."
    elif exc.code == 405:
        error_id, message = "ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route."
    elif exc.code == 400:
        error_id, message = "ERR_INVALID_REQUEST", "The request could not be parsed."
    else:
        error_id, message = "ERR_INTERNAL", exc.description or "Request failed."
    return jsonify(response.error_body(error_id, message)), exc.code


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return jsonify(response.error_body("ERR_INTERNAL", str(exc))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
