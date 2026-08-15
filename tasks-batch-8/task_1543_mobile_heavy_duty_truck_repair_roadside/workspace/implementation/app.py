"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error("ERR_NOT_FOUND", "Resource does not exist", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error("ERR_NOT_FOUND", "Resource does not exist", 404)

    @app.errorhandler(Exception)
    def handle_exception(exc):
        return error("ERR_INTERNAL", str(exc), 500)

    from routes.ops import bp as ops_bp
    from routes.fleets import bp as fleets_bp
    from routes.vehicles import bp as vehicles_bp
    from routes.technicians import bp as technicians_bp
    from routes.rate_cards import bp as rate_cards_bp
    from routes.van_stock import bp as van_stock_bp
    from routes.service_calls import bp as service_calls_bp
    from routes.dispatches import bp as dispatches_bp
    from routes.estimates import bp as estimates_bp
    from routes.part_usages import bp as part_usages_bp
    from routes.tow_orders import bp as tow_orders_bp
    from routes.warranty_claims import bp as warranty_claims_bp
    from routes.inspection_defects import bp as inspection_defects_bp
    from routes.invoices import bp as invoices_bp
    from routes.payments import bp as payments_bp
    from routes.repeat_failures import bp as repeat_failures_bp
    from routes.restock import bp as restock_bp
    from routes.call_events import bp as call_events_bp

    for bp in (ops_bp, fleets_bp, vehicles_bp, technicians_bp, rate_cards_bp,
               van_stock_bp, service_calls_bp, dispatches_bp, estimates_bp,
               part_usages_bp, tow_orders_bp, warranty_claims_bp,
               inspection_defects_bp, invoices_bp, payments_bp,
               repeat_failures_bp, restock_bp, call_events_bp):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
