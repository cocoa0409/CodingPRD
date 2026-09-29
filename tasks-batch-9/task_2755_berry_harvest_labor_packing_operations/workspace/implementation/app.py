"""Berry Harvest Ops API — Flask entry point.

Storage is entirely in memory (see db.py) and starts empty on every boot: the
harness relaunches this process before each test, so no state may survive.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import config
import db
import response
from errors import ApiError
from routes import blocks, crews, lots, sales, sessions, windows


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (blocks, crews, windows, sessions, lots, sales):
        app.register_blueprint(module.bp, url_prefix=config.API_PREFIX)

    # One request at a time: every handler reads and writes the shared tables.
    @app.before_request
    def _acquire_lock():
        db.LOCK.acquire()

    @app.teardown_request
    def _release_lock(exception=None):
        try:
            db.LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(error):
        if error.code == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "No such resource path.", 404
            )
        if error.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed on this path.", 405
            )
        if error.code == 415:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Unsupported media type.", 400
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", error.description or "Request rejected.", error.code
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % (error,), 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
