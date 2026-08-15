"""Flask application entry point."""

import os
import traceback

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.clock import bp as clock_bp
    from routes.plants import bp as plants_bp
    from routes.products import bp as products_bp
    from routes.stores import bp as stores_bp
    from routes.drivers import bp as drivers_bp
    from routes.lines import bp as lines_bp
    from routes.store_orders import bp as store_orders_bp
    from routes.production_plans import bp as production_plans_bp
    from routes.batches import bp as batches_bp
    from routes.sanitation_cycles import bp as sanitation_cycles_bp
    from routes.routes import bp as routes_bp
    from routes.route_stops import bp as route_stops_bp
    from routes.stale_returns import bp as stale_returns_bp
    from routes.thrift_sales import bp as thrift_sales_bp
    from routes.ingredient_indices import bp as ingredient_indices_bp
    from routes.surcharge_schedules import bp as surcharge_schedules_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(plants_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(stores_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(lines_bp)
    app.register_blueprint(store_orders_bp)
    app.register_blueprint(production_plans_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(sanitation_cycles_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(route_stops_bp)
    app.register_blueprint(stale_returns_bp)
    app.register_blueprint(thrift_sales_bp)
    app.register_blueprint(ingredient_indices_bp)
    app.register_blueprint(surcharge_schedules_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, f"Internal error: {err}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
