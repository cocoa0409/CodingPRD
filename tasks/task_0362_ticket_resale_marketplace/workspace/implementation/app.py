"""Ticket Resale Marketplace API — Flask entry point.

In-memory store starts empty on every boot (no seeding). The test harness
restarts this process before every test under per-test-server isolation.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
import response

from routes.clock_routes import bp as clock_bp
from routes.venues import bp as venues_bp
from routes.events import bp as events_bp
from routes.parties import bp as parties_bp
from routes.listings import bp as listings_bp
from routes.seats import bp as seats_bp
from routes.orders import bp as orders_bp
from routes.transfers import bp as transfers_bp
from routes.payouts import bp as payouts_bp
from routes.claims import bp as claims_bp
from routes.credits import bp as credits_bp
from routes.fraud import bp as fraud_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(venues_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(seats_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(credits_bp)
    app.register_blueprint(fraud_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> generic not found in the envelope shape
        return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return response.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Body parse failures etc. surface as generic invalid request
        return response.error_response("ERR_INVALID_REQUEST", e.description or "Bad request",
                                       e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
