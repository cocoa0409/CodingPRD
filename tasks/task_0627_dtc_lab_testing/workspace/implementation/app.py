"""DTC Lab Testing API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No entity is ever
seeded. start.sh re-invocation wipes all state (fresh process).
"""
import os

from flask import Flask

import db
from errors import ApiError
from response import error_response

# Route blueprints.
from routes.catalog import bp as catalog_bp
from routes.carts import bp as carts_bp
from routes.orders import bp as orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.physician_orders import bp as physician_orders_bp
from routes.appointments import bp as appointments_bp
from routes.home_kits import bp as home_kits_bp
from routes.specimens import bp as specimens_bp
from routes.lab_results import bp as lab_results_bp
from routes.referrals import bp as referrals_bp
from routes.analyzer_runs import bp as analyzer_runs_bp
from routes.payments import bp as payments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Start every process with empty tables and a default logical clock.
    db.reset()

    for bp in (
        catalog_bp, carts_bp, orders_bp, order_lines_bp, physician_orders_bp,
        appointments_bp, home_kits_bp, specimens_bp, lab_results_bp,
        referrals_bp, analyzer_runs_bp, payments_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
