"""Rack Jobber Consignment API — Flask entry point.

Registers error handlers and route blueprints, then serves 0.0.0.0:$PORT
(default 10000) in the foreground.
"""
import os

from flask import Flask

import response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return response.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return response.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return response.error(exc.error_id, exc.message, exc.http_status)
    return response.error("ERR_INVALID_REQUEST", str(exc), 400)


import routes_core
import routes_space
import routes_field
import routes_finance

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_space.bp)
app.register_blueprint(routes_field.bp)
app.register_blueprint(routes_finance.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
