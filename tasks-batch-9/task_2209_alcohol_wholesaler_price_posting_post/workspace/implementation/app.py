"""Alcohol wholesaler price posting service.

Flask application factory and process entry point. All state lives in process
memory (see store.py); relaunching this process wipes every byte of it.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import ALL_BLUEPRINTS
from store import request_lock

DEFAULT_PORT = 10000


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_lock():
        request_lock.acquire()

    @app.teardown_request
    def _release_lock(exception=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _not_found(error):
        return error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(error):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "The HTTP method is not allowed for this resource.",
            405,
        )

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if isinstance(error, HTTPException) and error.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be understood.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST",
            error.description or "The request could not be processed.",
            error.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(error):
        return error_response(
            "ERR_INTERNAL", "An unexpected internal error occurred: %s" % error, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False, debug=False)
