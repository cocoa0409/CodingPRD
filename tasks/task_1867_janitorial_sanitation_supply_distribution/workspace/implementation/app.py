"""Jan/San Distribution API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error as error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_facilities
import routes_products
import routes_usage
import routes_forecast
import routes_dispensers
import routes_standing_orders
import routes_orders
import routes_substitutions
import routes_bids
import routes_trials
import routes_ops

app.register_blueprint(routes_facilities.bp)
app.register_blueprint(routes_products.bp)
app.register_blueprint(routes_usage.bp)
app.register_blueprint(routes_forecast.bp)
app.register_blueprint(routes_dispensers.bp)
app.register_blueprint(routes_standing_orders.bp)
app.register_blueprint(routes_orders.bp)
app.register_blueprint(routes_substitutions.bp)
app.register_blueprint(routes_bids.bp)
app.register_blueprint(routes_trials.bp)
app.register_blueprint(routes_ops.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(400)
def handle_400(e):
    return error_response(ERR_VALIDATION, "Bad request", 400)


@app.errorhandler(500)
def handle_500(e):
    return error_response("ERR_INTERNAL", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
