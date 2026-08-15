"""Water Treatment Chemical Service API -- Flask entry point.

Boots cleanly from a fresh process; storage is in-memory only and starts
empty on every boot. Listens on 0.0.0.0:$PORT (default 10000).
"""

import os

from flask import Flask, g
from werkzeug.exceptions import NotFound, MethodNotAllowed

import errors
from errors import ApiError
from middleware import authenticate
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_clock
import routes_accounts
import routes_assets
import routes_designs
import routes_products
import routes_stations
import routes_routes
import routes_results
import routes_racks
import routes_plans
import routes_orders
import routes_invoices

for module in (routes_clock, routes_accounts, routes_assets, routes_designs,
               routes_products, routes_stations, routes_routes, routes_results,
               routes_racks, routes_plans, routes_orders, routes_invoices):
    app.register_blueprint(module.bp)


@app.before_request
def _auth():
    from flask import request
    if not request.path.startswith("/wt/"):
        return None
    user_id, role = authenticate()
    g.user_id = user_id
    g.role = role
    return None


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(NotFound)
def _not_found(err):
    return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(MethodNotAllowed)
def _method_not_allowed(err):
    return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def _unhandled(err):
    return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % err)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
