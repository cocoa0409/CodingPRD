"""Water Delivery & Bottled Water Service API — Flask entry point.

Mounts all blueprints under /api/v1, enforces the auth cascade
(PRD §2.6 stage 1), and renders the standard error envelope.
"""
import os

from flask import Flask, request

import errors
import middleware
from errors import ApiError
from response import error_response
from routes import (addons, clock_routes, customers, invoices, payments,
                    pricing, rentals, routes_stops, skip_credits, work_orders,
                    zones)

app = Flask(__name__)
app.url_map.strict_slashes = False

PREFIX = "/api/v1"

app.register_blueprint(clock_routes.bp, url_prefix=PREFIX)
app.register_blueprint(pricing.bp, url_prefix=PREFIX)
app.register_blueprint(zones.bp, url_prefix=PREFIX)
app.register_blueprint(customers.bp, url_prefix=PREFIX)
app.register_blueprint(routes_stops.bp, url_prefix=PREFIX)
app.register_blueprint(work_orders.bp, url_prefix=PREFIX)
app.register_blueprint(rentals.bp, url_prefix=PREFIX)
app.register_blueprint(addons.bp, url_prefix=PREFIX)
app.register_blueprint(invoices.bp, url_prefix=PREFIX)
app.register_blueprint(payments.bp, url_prefix=PREFIX)
app.register_blueprint(skip_credits.bp, url_prefix=PREFIX)


@app.before_request
def auth_gate():
    if not request.path.startswith(PREFIX):
        return None
    if request.path == PREFIX + "/_clock/set_current_utc":
        return None  # exempt: header presence is not required here
    middleware.extract_auth()
    return None


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(errors.not_found("resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(errors.not_found("resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
