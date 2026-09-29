"""Restaurant Brand Standards Audit API.

A Flask application over a purely in-memory store.  Every process boot starts
from an empty dataset and a logical clock reading 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response
from routes import actions, appeals, integrations, registry, rubrics, visits


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(registry.bp)
    app.register_blueprint(rubrics.bp)
    app.register_blueprint(visits.bp)
    app.register_blueprint(actions.bp)
    app.register_blueprint(appeals.bp)
    app.register_blueprint(integrations.bp)

    @app.before_request
    def _acquire():
        # Requests are serialized: the domain cascades touch many records and
        # must not interleave.
        db.request_lock.acquire()
        g._locked = True
        g._touched = set()

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            db.request_lock.release()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        status = error.code or 500
        if status == 404:
            message = "The requested resource does not exist."
        elif status == 405:
            message = "The HTTP method is not allowed for this path."
        else:
            message = error.description or "The request could not be processed."
        return error_response("ERR_INVALID_REQUEST", message, status)

    @app.errorhandler(Exception)
    def _unexpected(error):
        return error_response(
            "ERR_INVALID_REQUEST",
            "Unexpected server error: %s" % error,
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
