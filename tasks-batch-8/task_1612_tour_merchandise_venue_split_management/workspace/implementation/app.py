"""Tour Merchandise & Venue Split Management API — Flask application entry point."""

import os
from flask import Flask

from errors import ApiError, ERR_VALIDATION
from response import error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_VALIDATION, "Route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_VALIDATION, "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response(ERR_VALIDATION, f"Internal error: {e}", 500)


from routes.tours import bp as tours_bp
from routes.shows import bp as shows_bp
from routes.products import bp as products_bp
from routes.show_products import bp as show_products_bp
from routes.allocations import bp as allocations_bp
from routes.sellers import bp as sellers_bp
from routes.sessions import bp as sessions_bp
from routes.sale_records import bp as sale_records_bp
from routes.online_orders import bp as online_orders_bp
from routes.settlements import bp as settlements_bp
from routes.shipments import bp as shipments_bp
from routes.clock_admin import bp as clock_bp

app.register_blueprint(tours_bp)
app.register_blueprint(shows_bp)
app.register_blueprint(products_bp)
app.register_blueprint(show_products_bp)
app.register_blueprint(allocations_bp)
app.register_blueprint(sellers_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(sale_records_bp)
app.register_blueprint(online_orders_bp)
app.register_blueprint(settlements_bp)
app.register_blueprint(shipments_bp)
app.register_blueprint(clock_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
