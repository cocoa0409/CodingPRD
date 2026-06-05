"""Waste & Recycling Collection API — Flask entry point."""
import os

from flask import Flask

from errors import APIError
from response import error_response

from routes.accounts import bp as accounts_bp
from routes.carts import bp as carts_bp
from routes.service_plans import bp as service_plans_bp
from routes.routes_bp import bp as routes_bp
from routes.pickups import bp as pickups_bp
from routes.invoices import bp as invoices_bp
from routes.special_pickups import bp as special_pickups_bp
from routes.credits import bp as credits_bp
from routes.diversion_periods import bp as diversion_periods_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(carts_bp)
    app.register_blueprint(service_plans_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(pickups_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(special_pickups_bp)
    app.register_blueprint(credits_bp)
    app.register_blueprint(diversion_periods_bp)

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
        body = error_response("ERR_NOT_FOUND", "Method not allowed.")
        return body, 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected server-side faults as a generic 400 envelope rather
        # than Flask's HTML error page, so clients always parse JSON.
        if isinstance(exc, APIError):
            return handle_api_error(exc)
        body = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(exc))
        return body, 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
