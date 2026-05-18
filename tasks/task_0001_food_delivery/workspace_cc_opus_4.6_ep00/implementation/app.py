import os
from flask import Flask
from errors import AppError
from response import error_response
from middleware import check_auth

from routes.restaurants import bp as restaurants_bp
from routes.menu_items import bp as menu_items_bp
from routes.customers import bp as customers_bp
from routes.riders import bp as riders_bp
from routes.orders import bp as orders_bp
from routes.assignments import bp as assignments_bp
from routes.returns import bp as returns_bp
from routes.fines import bp as fines_bp
from routes.work_orders import bp as work_orders_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)

    @app.before_request
    def before_request():
        check_auth()

    @app.errorhandler(AppError)
    def handle_app_error(e):
        return error_response(e.error_id, e.message, e.status_code)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Not found", 404)

    app.register_blueprint(restaurants_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(riders_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(fines_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(clock_bp)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False)
