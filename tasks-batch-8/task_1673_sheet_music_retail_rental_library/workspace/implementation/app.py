"""Sheet Music Retail & Rental Library API — entry point.

Flask app, error handlers, blueprint registration. The store starts empty on
every boot; all state is in-memory and per-process (per-test-server isolation).
"""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response

from routes.system import bp as system_bp
from routes.publishers import bp as publishers_bp
from routes.works import bp as works_bp
from routes.rental_sets import bp as rental_sets_bp
from routes.accounts import bp as accounts_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.rental_orders import bp as rental_orders_bp
from routes.rental_lines import bp as rental_lines_bp
from routes.condition_reports import bp as condition_reports_bp
from routes.damage_invoices import bp as damage_invoices_bp
from routes.perusals import bp as perusals_bp
from routes.sales import bp as sales_bp
from routes.rights import bp as rights_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_INVALID_REQUEST, "Unknown path", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(ERR_INVALID_REQUEST, "Internal error: %s" % e, 500)

    for bp in (
        system_bp,
        publishers_bp,
        works_bp,
        rental_sets_bp,
        accounts_bp,
        purchase_orders_bp,
        rental_orders_bp,
        rental_lines_bp,
        condition_reports_bp,
        damage_invoices_bp,
        perusals_bp,
        sales_bp,
        rights_bp,
    ):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
