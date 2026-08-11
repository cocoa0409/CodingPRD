"""Entry point: app factory, error handlers, route registration.

The store starts empty on every boot; no entity is seeded anywhere.
"""
import os

from flask import Flask

from errors import (
    ERR_INTERNAL,
    ERR_NOT_FOUND,
    ApiError,
)
from response import error_response
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False
register_routes(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(exc):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_response(ERR_INTERNAL, 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
