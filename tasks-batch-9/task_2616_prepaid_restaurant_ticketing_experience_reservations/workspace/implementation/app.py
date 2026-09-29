"""Prepaid Restaurant Ticketing API — entry point.

Storage is in-memory only and the store starts completely empty on every boot:
no entity is seeded, preloaded or hardcoded here. Every row a caller sees was
created through a declared endpoint in this same process.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response
import routes_catalog
import routes_service
import routes_reservation
import routes_money


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes_catalog.register(app)
    routes_service.register(app)
    routes_reservation.register(app)
    routes_money.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_missing_route(err):
        return error_response(ApiError("ERR_VALIDATION", "no such route"))

    @app.errorhandler(405)
    def handle_bad_method(err):
        return error_response(ApiError("ERR_VALIDATION", "method not allowed"))

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return error_response(ApiError("ERR_VALIDATION", err.description))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_VALIDATION", str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
