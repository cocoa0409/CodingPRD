"""Premium Sports Hospitality Packages API.

In-memory only: every entity is created through the API, nothing is seeded and
nothing is persisted, so each fresh process starts from a completely empty world.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_events
import routes_packages
import routes_rights
import routes_sales
import routes_venue
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_events.bp)
    app.register_blueprint(routes_rights.bp)
    app.register_blueprint(routes_packages.bp)
    app.register_blueprint(routes_sales.bp)
    app.register_blueprint(routes_venue.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_missing_route(exc):
        return error_response("ERR_NOT_FOUND", "No such resource.", 404)

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed here.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
