"""Entry point: Flask app, route registration, global error handlers.

In-memory store only; no seeded entities at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from response import error as error_response

from routes.parks import bp as parks_bp
from routes.pricing import bp as pricing_bp
from routes.windows import bp as windows_bp
from routes.guests import bp as guests_bp
from routes.orders import bp as orders_bp
from routes.admissions import bp as admissions_bp
from routes.rentals import bp as rentals_bp
from routes.rainchecks import bp as rainchecks_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(parks_bp)
    app.register_blueprint(pricing_bp)
    app.register_blueprint(windows_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(admissions_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(rainchecks_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Unrouted paths / wrong methods surface as ERR_NOT_FOUND so the
        # envelope is always well-formed.
        if exc.code == 404 or exc.code == 405:
            return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")
        if exc.code == 400:
            return error_response(errors.ERR_INVALID_REQUEST, 422, "Bad request")
        return error_response(errors.ERR_INVALID_REQUEST, exc.code or 422,
                              exc.description or "Request error")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response(errors.ERR_INVALID_REQUEST, 422, str(exc))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
