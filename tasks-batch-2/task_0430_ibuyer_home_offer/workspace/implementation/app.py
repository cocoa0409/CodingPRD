"""iBuyer / Instant Home Offer API — Flask entry point.

In-memory storage only; no seeding at startup (the store is created empty in
db.py and every entity is built by the declared API surface). Boots cleanly
from a fresh process on every invocation.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.assessments import bp as assessments_bp
from routes.clock import bp as clock_bp
from routes.offers import bp as offers_bp
from routes.properties import bp as properties_bp
from routes.repair_line_items import bp as repair_line_items_bp
from routes.resales import bp as resales_bp
from routes.sellers import bp as sellers_bp
from routes.transactions import bp as transactions_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(sellers_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(repair_line_items_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(resales_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route — emit the standard not-found error envelope.
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        # Defensive: surface unexpected errors as a generic 400-style invalid request
        # would be wrong; use 500 with an internal envelope.
        return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
