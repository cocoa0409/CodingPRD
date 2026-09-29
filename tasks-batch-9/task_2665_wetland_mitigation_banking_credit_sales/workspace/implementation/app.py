"""Wetland Mitigation Banking API — application entrypoint.

Storage is in-memory only and every collection boots empty: the implementation
encodes the system (state machines, calculations, validations, endpoints) and
never the data. Every entity is created through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import banks, clock, monitoring, parties, releases, review, sales


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in (parties.bp, banks.bp, review.bp, releases.bp, monitoring.bp,
                      sales.bp, clock.bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if error.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "The HTTP method is not allowed on this resource.", 405)
        if error.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "The request body could not be parsed as JSON.", 400)
        return error_response("ERR_INVALID_REQUEST", error.description or "Request failed.",
                              error.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return error_response("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
