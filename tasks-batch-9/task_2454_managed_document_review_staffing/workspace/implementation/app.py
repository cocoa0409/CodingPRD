"""Managed Document Review Staffing API.

Storage is entirely in memory and completely empty on every boot: no seeding, no
preloading, no file or cache of any kind.  Every row is created by a client
through one of the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from middleware import authenticate
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    register_routes(app)

    @app.before_request
    def _before_request():
        # Ranks 1 and 2 run before any routing-specific logic.
        db.lock.acquire()
        try:
            authenticate()
        except BaseException:
            db.lock.release()
            raise

    @app.teardown_request
    def _teardown_request(_exception):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "No such resource.", 404)
        if error.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "That method is not allowed here.", 405)
        if error.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "The request payload could not be read.", 422)
        return error_response("ERR_INTERNAL", error.description or "Request failed.",
                              error.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(error):
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
