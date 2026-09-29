"""Home-Cook Meal Marketplace with Cottage-Food Compliance - entry point.

Storage is in-memory only and starts completely empty on every boot: no entity
is seeded, preloaded or hardcoded here. Tests build all state through the
declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_config
import routes_cooks
import routes_menu
import routes_money
import routes_orders
import routes_safety
import routes_windows
from core import ApiError, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes_config.bp)
app.register_blueprint(routes_cooks.bp)
app.register_blueprint(routes_menu.bp)
app.register_blueprint(routes_windows.bp)
app.register_blueprint(routes_orders.bp)
app.register_blueprint(routes_safety.bp)
app.register_blueprint(routes_money.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_error(err):
    if err.code == 404:
        return error_response(ApiError("ERR_NOT_FOUND", "the requested resource does not exist"))
    if err.code == 405:
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "the method is not allowed for this resource")
        )
    if err.code == 400:
        return error_response(ApiError("ERR_INVALID_REQUEST", "the request body is malformed"))
    return error_response(ApiError("ERR_INVALID_REQUEST", err.description or "request failed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, HTTPException):
        return handle_http_error(err)
    return error_response(ApiError("ERR_INTERNAL", str(err) or "internal error"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
