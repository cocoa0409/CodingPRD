"""Flask application entry point.

The store is in-memory and starts EMPTY on every boot: the harness relaunches
this process before every single test, so nothing may be seeded or persisted.
"""

import os

from flask import Flask, g, jsonify

import db
import routes
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes.register(app)

    @app.before_request
    def _acquire():
        db.LOCK.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                db.LOCK.release()
            except RuntimeError:  # pragma: no cover - defensive
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this route.", 405)

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - defensive
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        code = getattr(err, "code", None)
        if code == 404:
            return error_response("ERR_NOT_FOUND",
                                  "The requested route does not exist.", 404)
        if code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this route.", 405)
        if code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be understood.", 400)
        return error_response("ERR_INTERNAL", str(err) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
