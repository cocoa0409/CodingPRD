"""Non-Alcoholic Bottle Shop API — Flask entry point.

In-memory only (dicts keyed by id); store starts empty on every boot.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error as error_response
from routes import (admin, categories, clubs, members, orders, shipping_rules,
                    skus, special_orders, tastings)

app = Flask(__name__)
app.url_map.strict_slashes = False

API_PREFIX = "/nabs"

for module in (categories, skus, members, clubs, tastings, special_orders,
               orders, shipping_rules, admin):
    app.register_blueprint(module.bp, url_prefix=API_PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_INVALID_REQUEST, "Malformed request", 400)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response(ERR_INVALID_REQUEST, "Malformed request", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
