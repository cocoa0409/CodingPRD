"""Flask app factory and entry point for the Online Auction & Bidding Marketplace API.

Registers every route blueprint and installs the global error handler that renders
ApiError instances into the standard error envelope (PRD §2.2). Storage is purely
in-memory (see db.py); nothing is seeded at startup.
"""
import os

from flask import Flask

import errors
import response
from routes.accounts import bp as accounts_bp
from routes.listings import bp as listings_bp
from routes.bids import bp as bids_bp
from routes.watches import bp as watches_bp
from routes.offers import bp as offers_bp
from routes.orders import bp as orders_bp
from routes.invoices import bp as invoices_bp
from routes.feedback import bp as feedback_bp
from routes.disputes import bp as disputes_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(bids_bp)
    app.register_blueprint(watches_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        # Unknown route — treat as a not-found resource per the error catalogue.
        return response.error(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return response.error(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface unexpected errors as a generic invalid-request rather than an
        # HTML 500 page, so the test harness always sees the JSON envelope.
        if isinstance(err, errors.ApiError):
            return response.error(err.error_id, err.message, err.http_status)
        return response.error(errors.ERR_INVALID_REQUEST, str(err), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
