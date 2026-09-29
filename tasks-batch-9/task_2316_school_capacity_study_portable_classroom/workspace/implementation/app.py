"""School Capacity Portable Allocation API.

Flask application factory and error envelope handlers.  All state lives in
memory (see db.py) and the store is empty on every boot: nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERROR_HTTP
from response import error
from routes.config import bp as config_bp
from routes.disposals import bp as disposals_bp
from routes.permits import bp as permits_bp
from routes.requests import bp as requests_bp
from routes.schedules import bp as schedules_bp
from routes.studies import bp as studies_bp
from routes.units import bp as units_bp

API_PREFIX = "/facilities"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (config_bp, studies_bp, units_bp, requests_bp,
                      permits_bp, schedules_bp, disposals_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "No such resource.",
                         ERROR_HTTP["ERR_NOT_FOUND"])
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED",
                         "That method is not allowed on this resource.",
                         ERROR_HTTP["ERR_METHOD_NOT_ALLOWED"])
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request could not be read.",
                         ERROR_HTTP["ERR_INVALID_REQUEST"])
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INTERNAL", "Internal server error: %s" % exc,
                     ERROR_HTTP["ERR_INTERNAL"])

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
