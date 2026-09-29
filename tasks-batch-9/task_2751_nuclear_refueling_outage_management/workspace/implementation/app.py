"""Nuclear Refueling Outage Management API.

Entry point: registers every route blueprint and the error handlers.  The store
is in-memory and starts completely empty on every boot -- no seeding anywhere.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
import routes_config
import routes_emergent
import routes_fuel
import routes_outage
import routes_rwp
import routes_schedule
import routes_startup
import routes_workforce
import routes_workorder


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (routes_config, routes_outage, routes_workorder, routes_schedule,
                   routes_fuel, routes_workforce, routes_rwp, routes_emergent,
                   routes_startup):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Method not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request body or query is malformed.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return handle_http_exception(exc)
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
