"""Truck Body Upfitting & Final Stage Manufacturing API.

Entry point: registers every blueprint, installs the error handlers that render
the PRD's error envelope, and serves on 0.0.0.0:$PORT in the foreground.

The store is in-memory and starts completely empty on every boot; no entity is
ever seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.catalog import catalog_bp
from routes.certifications import certifications_bp
from routes.chassis_routes import chassis_bp
from routes.claims import claims_bp
from routes.clock_routes import clock_bp
from routes.configurations import configurations_bp
from routes.installations import installations_bp
from routes.interfaces import interfaces_bp
from routes.labels import labels_bp
from routes.orders import orders_bp
from routes.slots import slots_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(configurations_bp)
    app.register_blueprint(chassis_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(installations_bp)
    app.register_blueprint(interfaces_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(certifications_bp)
    app.register_blueprint(labels_bp)
    app.register_blueprint(claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "No such route.", 404
            )
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this route.", 405
            )
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 422
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
