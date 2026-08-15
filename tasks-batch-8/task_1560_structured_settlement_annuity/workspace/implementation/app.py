"""Entry point: registers blueprints, error handlers, and runs the server."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
import routes_core
import routes_structuring
import routes_payments
import routes_changes
import routes_transfers
import routes_claims


def create_app():
    app = Flask(__name__)

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_structuring.bp)
    app.register_blueprint(routes_payments.bp)
    app.register_blueprint(routes_changes.bp)
    app.register_blueprint(routes_transfers.bp)
    app.register_blueprint(routes_claims.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
