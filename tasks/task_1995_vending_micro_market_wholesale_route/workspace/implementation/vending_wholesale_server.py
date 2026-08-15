"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask, jsonify
import clock
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.json.sort_keys = False

from routes import (
    operators, delivery_routes, products, locations, planograms,
    promotions, telemetry, orders, credit_claims, service_tickets, clock_routes,
)

app.register_blueprint(operators.bp)
app.register_blueprint(delivery_routes.bp)
app.register_blueprint(products.bp)
app.register_blueprint(locations.bp)
app.register_blueprint(planograms.bp)
app.register_blueprint(promotions.bp)
app.register_blueprint(telemetry.bp)
app.register_blueprint(orders.bp)
app.register_blueprint(credit_claims.bp)
app.register_blueprint(service_tickets.bp)
app.register_blueprint(clock_routes.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(e):
    err = ApiError("ERR_INVALID_REQUEST", 404, "Resource not found")
    return error_response(err)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    err = ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed")
    return error_response(err)


@app.errorhandler(400)
def handle_bad_request(e):
    if isinstance(e, ApiError):
        return error_response(e)
    err = ApiError("ERR_INVALID_REQUEST", 400, "Malformed request")
    return error_response(err)


@app.errorhandler(Exception)
def handle_unexpected(e):
    err = ApiError("ERR_INVALID_REQUEST", 500, f"Internal error: {e}")
    return error_response(err)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
