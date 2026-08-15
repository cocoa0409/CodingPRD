"""Flask application entry point: route registration and error handling."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.jurisdictions import bp as jurisdictions_bp
from routes.models import bp as models_bp
from routes.customers import bp as customers_bp
from routes.orders import bp as orders_bp
from routes.payments import bp as payments_bp
from routes.assessments import bp as assessments_bp
from routes.permits import bp as permits_bp
from routes.tickets import bp as tickets_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    for bp in (jurisdictions_bp, models_bp, customers_bp, orders_bp, payments_bp,
               assessments_bp, permits_bp, tickets_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response(ERR_NOT_FOUND, "Referenced resource does not exist", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response(ERR_NOT_FOUND, "Referenced resource does not exist", 404)

    @app.errorhandler(400)
    def handle_400(_err):
        return error_response(ERR_INVALID_REQUEST,
                              "Missing required field, malformed value, or invalid enum member",
                              400)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response(ERR_INVALID_REQUEST, str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
