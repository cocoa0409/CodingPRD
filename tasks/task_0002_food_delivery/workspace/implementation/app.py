"""Food Delivery Platform API — Flask entry point."""

import os
from flask import Flask
from errors import ApiError
from response import error_response

app = Flask(__name__)


# ---- Global error handler ----
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)


@app.errorhandler(500)
def handle_500(exc):
    return error_response("ERR_INTERNAL", str(exc), 500)


# ---- Register blueprints ----
from routes.restaurants import bp as restaurants_bp
from routes.customers import bp as customers_bp
from routes.riders import bp as riders_bp
from routes.orders import bp as orders_bp
from routes.deliveries import bp as deliveries_bp
from routes.ratings import bp as ratings_bp
from routes.complaints import bp as complaints_bp
from routes.promotions import bp as promotions_bp
from routes.surge_zones import bp as surge_zones_bp
from routes.settlements import bp as settlements_bp

app.register_blueprint(restaurants_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(riders_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(deliveries_bp)
app.register_blueprint(ratings_bp)
app.register_blueprint(complaints_bp)
app.register_blueprint(promotions_bp)
app.register_blueprint(surge_zones_bp)
app.register_blueprint(settlements_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
