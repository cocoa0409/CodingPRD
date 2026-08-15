"""Dairy Distribution & DSD Route API — Flask application entry point."""

import os
from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)
app.json.sort_keys = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_INVALID_REQUEST, "Route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response(ERR_INVALID_REQUEST, f"Internal error: {e}", 500)


# Register route blueprints
from routes.clock_admin import bp as clock_bp
from routes.distributors import bp as distributors_bp
from routes.dairy_routes import bp as dairy_routes_bp
from routes.drivers import bp as drivers_bp
from routes.stores import bp as stores_bp
from routes.products import bp as products_bp
from routes.pars import bp as pars_bp
from routes.pricing import bp as pricing_bp
from routes.trips import bp as trips_bp
from routes.readings import bp as readings_bp
from routes.orders import bp as orders_bp
from routes.invoices import bp as invoices_bp
from routes.returns import bp as returns_bp
from routes.credit_memos import bp as credit_memos_bp
from routes.crates import bp as crates_bp
from routes.merch import bp as merch_bp
from routes.listings import bp as listings_bp

app.register_blueprint(clock_bp)
app.register_blueprint(distributors_bp)
app.register_blueprint(dairy_routes_bp)
app.register_blueprint(drivers_bp)
app.register_blueprint(stores_bp)
app.register_blueprint(products_bp)
app.register_blueprint(pars_bp)
app.register_blueprint(pricing_bp)
app.register_blueprint(trips_bp)
app.register_blueprint(readings_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(invoices_bp)
app.register_blueprint(returns_bp)
app.register_blueprint(credit_memos_bp)
app.register_blueprint(crates_bp)
app.register_blueprint(merch_bp)
app.register_blueprint(listings_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
