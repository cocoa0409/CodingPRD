import os

from flask import Flask

import db
import response
from errors import ApiError
from middleware import require_roles
from util import get_json_body, parse_iso

from routes.vehicles import bp as vehicles_bp
from routes.floor_plan_lines import bp as floor_plan_bp
from routes.customers import bp as customers_bp
from routes.config_catalogs import bp as config_bp
from routes.deals import bp as deals_bp
from routes.deal_subresources import bp as deal_sub_bp
from routes.test_drives import bp as test_drives_bp
from routes.repair_orders import bp as repair_orders_bp
from routes.title_registrations import bp as title_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(vehicles_bp)
    app.register_blueprint(floor_plan_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(deals_bp)
    app.register_blueprint(deal_sub_bp)
    app.register_blueprint(test_drives_bp)
    app.register_blueprint(repair_orders_bp)
    app.register_blueprint(title_bp)

    @app.post("/_clock/set_current_utc")
    @require_roles("InventoryClerk", "FinanceManager", "SalesManager", "ServiceAdvisor", "TitleClerk")
    def set_clock():
        body = get_json_body()
        raw = body.get("to_iso8601")
        if raw is None:
            from errors import err
            raise err("ERR_INVALID_REQUEST", "to_iso8601 is required")
        dt = parse_iso(raw, "to_iso8601")
        db.set_current_utc(dt)
        return response.success({"now": db.format_iso(dt)}, status=200)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return response.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return response.error(e.error_id, e.http_status, e.message)
        return response.error("ERR_INVALID_REQUEST", 422, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve with waitress (a production WSGI server) when available: Werkzeug's
    # dev server can reset/abort connections under heavy concurrent host load
    # (8 server processes booting + serving at once), surfacing as a flaky
    # BadStatusLine on the client. waitress has a robust accept/serve loop.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
