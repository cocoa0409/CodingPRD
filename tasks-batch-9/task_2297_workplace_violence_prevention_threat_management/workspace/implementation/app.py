"""Workplace Violence Prevention & Threat Management API.

Boots with a completely empty in-memory store on every invocation: no entity is
seeded, preloaded or hardcoded anywhere in this package.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import request_lock  # noqa: E402
from errors import ApiError  # noqa: E402
from response import error_response  # noqa: E402
from routes import BLUEPRINTS  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # The store is a plain dict graph, so requests are serialised.
    @app.before_request
    def _acquire():
        request_lock.acquire()

    @app.teardown_request
    def _release(exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response("ERR_INVALID_REQUEST", "No such route.", 404)
        if error.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if error.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_response("ERR_INVALID_REQUEST", error.description or "Request failed.",
                              error.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(error):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
