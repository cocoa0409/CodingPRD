import os

from flask import Flask

from errors import ApiError, err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock_routes import clock_bp
from routes.bike_models import bike_models_bp
from routes.bikes import bikes_bp
from routes.accounts import accounts_bp
from routes.rentals import rentals_bp
from routes.deliveries import deliveries_bp
from routes.service_tickets import service_tickets_bp
from routes.coverage_claims import coverage_claims_bp
from routes.inspection_reports import inspection_reports_bp
from routes.buyout_offers import buyout_offers_bp
from routes.fleet_invoices import fleet_invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(bike_models_bp)
    app.register_blueprint(bikes_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(deliveries_bp)
    app.register_blueprint(service_tickets_bp)
    app.register_blueprint(coverage_claims_bp)
    app.register_blueprint(inspection_reports_bp)
    app.register_blueprint(buyout_offers_bp)
    app.register_blueprint(fleet_invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
