"""Race Timing Results API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import (
    ApiError,
    ERR_INTERNAL,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)
from response import error_response
from routes import register_blueprints

app = Flask(__name__)
register_blueprints(app)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(400)
def handle_400(e):
    return error_response(ERR_INVALID_REQUEST, "Bad request", 400)


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.status)
    if isinstance(e, HTTPException):
        status = e.code if e.code and 400 <= e.code < 600 else 500
        error_id = ERR_INVALID_REQUEST if status < 500 else ERR_INTERNAL
        return error_response(error_id, e.description, status)
    return error_response(ERR_INTERNAL, "Internal server error: {}".format(e), 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
