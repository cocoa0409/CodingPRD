"""Hospital Case Management & Discharge Planning API.

Entry point: registers the route blueprints, installs the global error
handler and the authentication hook, and serves on 0.0.0.0:$PORT.

The store is in-memory only and starts completely empty on every boot -- no
entity is ever seeded, preloaded or hardcoded at startup.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_authorization
import routes_clinical
import routes_episode
import routes_logistics
import routes_placement
import routes_registry
from envelope import error_response
from errors import ApiError
from validate import authenticate


class SerializeRequests(object):
    """Each request is applied atomically against the in-memory store, so a
    multi-step check-then-commit (bed holds, vehicle windows, ledgers) can
    never interleave with a concurrent writer."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.RLock()

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_episode.bp)
    app.register_blueprint(routes_clinical.bp)
    app.register_blueprint(routes_placement.bp)
    app.register_blueprint(routes_authorization.bp)
    app.register_blueprint(routes_logistics.bp)

    @app.before_request
    def _auth():
        # PRD 2.1: this check runs before path resolution, before body
        # parsing and before any state inspection.
        authenticate()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_VALIDATION", "unknown route", 404))
        if err.code == 405:
            return error_response(ApiError("ERR_VALIDATION", "method not allowed", 405))
        return error_response(ApiError("ERR_VALIDATION", str(err), err.code or 400))

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_response(ApiError("ERR_VALIDATION", "unexpected error: %s" % err, 400))

    app.wsgi_app = SerializeRequests(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
