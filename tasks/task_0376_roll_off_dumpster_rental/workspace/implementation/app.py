"""Roll-Off Dumpster Rental API — entry point and route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.container_types import bp as container_types_bp
from routes.contractor_accounts import bp as contractor_accounts_bp
from routes.containers import bp as containers_bp
from routes.rental_orders import bp as rental_orders_bp
from routes.routes_bp import bp as routes_bp
from routes.service_stops import bp as service_stops_bp
from routes.weigh_tickets import bp as weigh_tickets_bp
from routes.street_permits import bp as street_permits_bp
from routes.invoices import bp as invoices_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(container_types_bp)
    app.register_blueprint(contractor_accounts_bp)
    app.register_blueprint(containers_bp)
    app.register_blueprint(rental_orders_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(service_stops_bp)
    app.register_blueprint(weigh_tickets_bp)
    app.register_blueprint(street_permits_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route path — not a modeled resource not-found.
        return error_response("ERR_INVALID_REQUEST", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 500, "Internal error: %s" % e)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
