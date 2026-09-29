"""Commercial Tire Program & Retread Management API.

Single Flask process, in-memory dict storage, zero persistence, zero seeding:
every fresh boot starts with completely empty collections.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import routes_core
import routes_plant
import routes_service
import routes_tire
from errors import ApiError
from response import error as error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_tire.bp)
    app.register_blueprint(routes_plant.bp)
    app.register_blueprint(routes_service.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                errors.ERR_NOT_FOUND, "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                errors.ERR_METHOD_NOT_ALLOWED,
                "The HTTP method is not allowed for this resource.",
                405,
            )
        if exc.code in (400, 415):
            return error_response(
                errors.ERR_INVALID_REQUEST, "The request is malformed.", 400
            )
        return error_response(
            errors.ERR_INTERNAL, exc.description or "Unexpected error.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response(errors.ERR_INTERNAL, "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
