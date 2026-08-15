"""Payroll Garnishment & Wage Order Processing API — Flask entry point."""

import os
import traceback

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from middleware import authenticate
from response import error_response
from routes import register_all

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _authenticate():
    # Priority 1 validation applies to every request.
    authenticate()


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _not_found(_exc):
    return error_response(ERR_NOT_FOUND, "The requested resource does not exist.", 404)


@app.errorhandler(405)
def _method_not_allowed(_exc):
    return error_response(ERR_NOT_FOUND, "The requested resource does not exist.", 404)


@app.errorhandler(Exception)
def _internal_error(exc):
    traceback.print_exc()
    return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)


register_all(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
