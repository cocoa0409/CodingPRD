"""Tree Service & Arborist API — Flask entry point.

In-memory store only; no seeding at startup. Boots clean on every invocation.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from errors import ApiError
from routes.bookings import bp as bookings_bp
from routes.disposal import bp as disposal_bp
from routes.estimates import bp as estimates_bp
from routes.permits import bp as permits_bp
from routes.resources import bp as resources_bp
from routes.work_orders import bp as work_orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(resources_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(estimates_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(disposal_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unmatched route -> generic invalid request (no entity context).
        return response.error(errors.ERR_INVALID_REQUEST, 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error(errors.ERR_INVALID_REQUEST, 405, "Method not allowed.")

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return response.error(errors.ERR_INVALID_REQUEST, exc.code or 500, exc.description)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", 500, str(exc))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
