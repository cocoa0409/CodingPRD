"""DMC Ground Operations API — Flask application factory and entry point.

State lives in process memory only (see store.py) and starts completely empty
on every boot: nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError, ERROR_STATUS

import routes_elements
import routes_programs
import routes_settlement
import routes_staff
import routes_transport
import routes_vendor


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_programs.bp)
    app.register_blueprint(routes_vendor.bp)
    app.register_blueprint(routes_elements.bp)
    app.register_blueprint(routes_transport.bp)
    app.register_blueprint(routes_staff.bp)
    app.register_blueprint(routes_settlement.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED",
                         "The method is not allowed for this route.", 405)
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error("ERR_INTERNAL", exc.description or "Unexpected error.",
                     exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
