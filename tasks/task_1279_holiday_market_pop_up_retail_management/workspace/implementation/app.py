"""Holiday Market API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only; the store is
empty at every boot and the logical clock starts at 2026-08-01T00:00:00Z.
"""
import os
import traceback

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes import register_blueprints

app = Flask(__name__)
register_blueprints(app)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ApiError("ERR_NOT_FOUND", "method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    return error_response(ApiError("ERR_INTERNAL", "internal server error", 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
