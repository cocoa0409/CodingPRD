"""Internet/Broadband Service Provisioning API — Flask entry point.

In-memory storage only (db.py module-level dicts); state is wiped on every
fresh process boot. Nothing is seeded at startup — tests build all state via
the API surface.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.catalogs import bp as catalogs_bp
from routes.equipment import bp as equipment_bp
from routes.accounts import bp as accounts_bp
from routes.service_orders import bp as service_orders_bp
from routes.scheduling import bp as scheduling_bp
from routes.billing import bp as billing_bp
from routes.outages import bp as outages_bp
from routes.transfers import bp as transfers_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalogs_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(service_orders_bp)
    app.register_blueprint(scheduling_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(outages_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / unresolved path -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            code = exc.code or 500
            if code == 404:
                return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
            if code == 405:
                return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)
            if code == 400:
                return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
            return error_response("ERR_INVALID_REQUEST", str(exc), code)
        return error_response("ERR_INVALID_REQUEST",
                              "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
