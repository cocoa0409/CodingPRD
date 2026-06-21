"""Bar Beverage Inventory API — Flask entry point.

In-memory storage only; the store is created fresh on every process boot (see
db.py) — no seeding, no preload, no disk persistence. start.sh re-invocation
wipes all state because nothing is persisted.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

# Blueprints (one module per resource group)
from routes.products import bp as products_bp
from routes.par_settings import bp as par_settings_bp
from routes.recipes import bp as recipes_bp
from routes.menu_items import bp as menu_items_bp
from routes.count_sessions import bp as count_sessions_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.invoices import bp as invoices_bp
from routes.waste_logs import bp as waste_logs_bp
from routes.keg_taps import bp as keg_taps_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(products_bp)
    app.register_blueprint(par_settings_bp)
    app.register_blueprint(recipes_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(count_sessions_bp)
    app.register_blueprint(purchase_orders_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(waste_logs_bp)
    app.register_blueprint(keg_taps_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: {}".format(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
