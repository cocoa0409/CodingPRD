"""Electric Utility Billing API — Flask entry point.

Registers all resource blueprints and the global error handlers that render the
standard error envelope (PRD §2.2). The in-memory store (db.py) starts empty on
every boot; no entities are seeded.
"""
import os

from flask import Flask

from errors import APIError
from response import error_response

from routes.tariffs import bp as tariffs_bp
from routes.accounts import bp as accounts_bp
from routes.meters import bp as meters_bp
from routes.meter_reads import bp as meter_reads_bp
from routes.bills import bp as bills_bp
from routes.payments import bp as payments_bp
from routes.service_orders import bp as service_orders_bp
from routes.budget_plans import bp as budget_plans_bp
from routes.assistance_grants import bp as assistance_grants_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(tariffs_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(meters_bp)
    app.register_blueprint(meter_reads_bp)
    app.register_blueprint(bills_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(service_orders_bp)
    app.register_blueprint(budget_plans_bp)
    app.register_blueprint(assistance_grants_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        return body, exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        body = error_response("ERR_NOT_FOUND", "Resource not found.")
        return body, 404

    @app.errorhandler(405)
    def handle_405(exc):
        # Method not allowed on a known path. Surface as a not-found-style
        # envelope so clients always parse JSON.
        body = error_response("ERR_NOT_FOUND", "Method not allowed.")
        return body, 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, APIError):
            return handle_api_error(exc)
        body = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(exc))
        return body, 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
