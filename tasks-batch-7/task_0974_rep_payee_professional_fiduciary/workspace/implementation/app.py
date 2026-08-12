"""Entry point: Flask app, error handlers, blueprint registration."""

import os
import traceback

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.clients import bp as clients_bp
from routes.entitlements import bp as entitlements_bp
from routes.accounts import bp as accounts_bp
from routes.budget_plans import bp as budget_plans_bp
from routes.disbursements import bp as disbursements_bp
from routes.deposits import bp as deposits_bp
from routes.court_orders import bp as court_orders_bp
from routes.bonds import bp as bonds_bp
from routes.reports import bp as reports_bp
from routes.spend_down import bp as spend_down_bp
from routes.audits import bp as audits_bp
from routes.conservators import bp as conservators_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clients_bp, entitlements_bp, accounts_bp, budget_plans_bp,
        disbursements_bp, deposits_bp, court_orders_bp, bonds_bp,
        reports_bp, spend_down_bp, audits_bp, conservators_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
