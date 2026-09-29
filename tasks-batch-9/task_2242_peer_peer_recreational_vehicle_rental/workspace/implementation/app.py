"""RV Share Marketplace API — Flask application entry point.

Storage is in-memory only and empty at boot: no file, no cache, no seed data.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_bookings
import routes_claims
import routes_core
import routes_delivery
import routes_listings
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for module in (routes_core, routes_listings, routes_bookings,
                   routes_delivery, routes_claims):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "No such endpoint.", 404)
        if error.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this endpoint.", 405)
        if error.code and 400 <= error.code < 500:
            return error_response("ERR_INVALID_REQUEST",
                                  error.description or "Malformed request.", 400)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def _unexpected(error):
        return error_response("ERR_INTERNAL", "Internal server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
