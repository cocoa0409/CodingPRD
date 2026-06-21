"""Season Ticket Holder Management API — Flask entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.inventory import bp as inventory_bp
from routes.accounts import bp as accounts_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.seat_assignments import bp as seat_assignments_bp
from routes.payments import bp as payments_bp
from routes.transfers import bp as transfers_bp
from routes.parking import bp as parking_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(inventory_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(seat_assignments_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(parking_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = error_response(e.error_id, e.message)
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        body = error_response("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(e):
        body = error_response("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
        return jsonify(body), 422

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
