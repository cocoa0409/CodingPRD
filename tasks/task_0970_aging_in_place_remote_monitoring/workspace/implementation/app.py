"""Aging In Place Monitoring API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from response import error_resp
from routes import register_routes

app = Flask(__name__)
app.json.sort_keys = False
register_routes(app)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_resp(e)


@app.errorhandler(HTTPException)
def _handle_http(e):
    if e.code in (404, 405):
        return error_resp(errors.not_found("Resource not found"))
    return error_resp(errors.invalid_request("Bad request"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    return error_resp(ApiError("ERR_INVALID_REQUEST", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
