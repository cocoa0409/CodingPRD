"""Art Auction Consignment API — Flask entry point.

In-memory only. The store starts EMPTY on every boot; nothing is seeded.
The per-test-server harness relaunches start.sh (a fresh process) before each
test, which wipes all state.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Route blueprints
from routes.premium_schedules import bp as premium_schedules_bp
from routes.sellers import bp as sellers_bp
from routes.bidders import bp as bidders_bp
from routes.consignments import bp as consignments_bp
from routes.auction_sales import bp as auction_sales_bp
from routes.lots import bp as lots_bp
from routes.bids import bp as bids_bp
from routes.paddle_registrations import bp as paddle_registrations_bp
from routes.settlement import bp as settlement_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(premium_schedules_bp)
    app.register_blueprint(sellers_bp)
    app.register_blueprint(bidders_bp)
    app.register_blueprint(consignments_bp)
    app.register_blueprint(auction_sales_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(bids_bp)
    app.register_blueprint(paddle_registrations_bp)
    app.register_blueprint(settlement_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path id not resolved at routing layer.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other werkzeug HTTP error (e.g. malformed JSON -> 400).
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 400)
        return error_response("ERR_INVALID_REQUEST", e.description or "Error", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)

    @app.after_request
    def _close_connection(response):
        # Transport hygiene only: the per-test-server harness reuses a pooled
        # keep-alive client socket across the threaded Werkzeug dev server's
        # connection teardown, which can intermittently surface as a
        # BadStatusLine / ConnectionError race. Forcing Connection: close
        # prevents socket reuse. No endpoint, field, status code, error_id,
        # state transition, or calculation is affected.
        response.headers["Connection"] = "close"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
