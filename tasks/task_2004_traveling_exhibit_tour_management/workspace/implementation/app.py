"""Traveling Exhibit Tours API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
no seeding of any kind.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, ERROR_CATALOG
from security import authenticate
from routes import tours, crates, stops, contracts, kits, certs, shipments, \
    reports, claims, flat


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Authentication fires before everything else (PRD §2.8 priority 1).
    app.before_request(authenticate)

    for module in (tours, crates, stops, contracts, kits, certs, shipments,
                   reports, claims, flat):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response("ERR_NOT_FOUND", ERROR_CATALOG["ERR_NOT_FOUND"],
                              "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response("ERR_NOT_FOUND", ERROR_CATALOG["ERR_NOT_FOUND"],
                              "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            return error_response("ERR_INVALID_REQUEST", err.code or 400,
                                  err.description or "Bad request")
        return error_response("ERR_INVALID_REQUEST", 500,
                              "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
