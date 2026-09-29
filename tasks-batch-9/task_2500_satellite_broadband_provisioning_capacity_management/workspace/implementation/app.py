"""Satellite Broadband Provisioning & Capacity Management API.

A single Flask process holding all state in memory.  The store is empty on every
boot: no data is seeded, preloaded or hardcoded anywhere.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_hardware
import routes_impairment
import routes_regulatory
import routes_retail
import routes_roaming
import routes_service
import routes_topology
from auth import authenticate
from errors import ERROR_STATUS, ApiError
from response import error_response


class SerializingMiddleware(object):
    """One request at a time.

    The store is a plain dict graph and several workflows read a ledger, decide
    against it and then write; serialising requests keeps those read-decide-write
    sequences atomic, which is what the optimistic-concurrency contract of §2.6
    assumes.
    """

    def __init__(self, application):
        self.application = application
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            result = self.application(environ, start_response)
            # The response body is materialised inside the lock so that no
            # serialisation reads a half-mutated store.
            return list(result)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        routes_regulatory,
        routes_topology,
        routes_retail,
        routes_hardware,
        routes_service,
        routes_roaming,
        routes_impairment,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _authenticate():
        """Priority 1 of §2.11, applied uniformly to every declared endpoint."""
        authenticate()

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
        status = error.code or 500
        error_id = {400: "ERR_INVALID_REQUEST", 404: "ERR_NOT_FOUND",
                    405: "ERR_METHOD_NOT_ALLOWED"}.get(status, "ERR_INTERNAL")
        if error_id not in ERROR_STATUS:  # pragma: no cover
            error_id = "ERR_INTERNAL"
        return error_response(error_id, error.description or error_id, status)

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
