"""Healthcare Group Purchasing & Contract Compliance API.

Flask application factory and entry point. All state lives in memory in
db.Database; nothing is seeded and nothing is persisted to disk, so a fresh
process always starts with eleven empty entity collections.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.activations import activations_bp
from routes.clock import clock_bp
from routes.commitments import commitments_bp
from routes.contracts import contracts_bp
from routes.fees import fees_bp
from routes.files import files_bp
from routes.measurements import measurements_bp
from routes.members import members_bp
from routes.reviews import reviews_bp
from routes.xrefs import xrefs_bp

BLUEPRINTS = (
    clock_bp,
    contracts_bp,
    members_bp,
    reviews_bp,
    commitments_bp,
    xrefs_bp,
    activations_bp,
    files_bp,
    measurements_bp,
    fees_bp,
)

_REQUEST_LOCK = threading.Lock()


class SerializedRequests(object):
    """Serialize request handling so cascades never interleave."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _REQUEST_LOCK:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this resource.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request body or query string is invalid.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be handled.", exc.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "An unexpected internal error occurred.", 500)

    app.wsgi_app = SerializedRequests(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
