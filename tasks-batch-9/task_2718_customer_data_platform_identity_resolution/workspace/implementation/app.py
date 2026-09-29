"""Customer Data Platform & Identity Resolution API — Flask application factory.

Storage is in-memory only and starts completely empty on every boot.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import middleware
import response
from errors import ApiError
from routes import audience, consent, erasure, graph, sources, system

BLUEPRINTS = (
    system.bp,
    sources.bp,
    graph.bp,
    consent.bp,
    audience.bp,
    erasure.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _authenticate():
        if request.method == "OPTIONS":
            return None
        middleware.load_actor()
        return None

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(400)
    def _bad_request(_error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request body could not be parsed.", 400
        )

    @app.errorhandler(404)
    def _not_found(_error):
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(error):
        return response.error_response(
            "ERR_INVALID_REQUEST", error.description or "Request rejected.", error.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return _api_error(error)
        if isinstance(error, HTTPException):
            return _http_error(error)
        app.logger.exception("Unhandled error: %s", error)
        return response.error_response(
            "ERR_INTERNAL", "An unexpected error occurred.", 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
