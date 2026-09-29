"""Brand Safety & Ad Verification Operations -- application entry point.

The store lives in process memory only and starts completely EMPTY on every
boot: nothing is seeded, preloaded, registered or hardcoded.  Every entity a
caller needs is created through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import claims, core, lists, measurement, pages


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover -- older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(core.bp)
    app.register_blueprint(lists.bp)
    app.register_blueprint(pages.bp)
    app.register_blueprint(measurement.bp)
    app.register_blueprint(claims.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error_response(
            "ERR_NOT_FOUND", "No route matches the requested path.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this resource.", 405
        )

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request could not be understood.", 422
        )

    @app.errorhandler(415)
    def handle_unsupported_media(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request body must be JSON.", 422
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "No route matches the requested path.", 404
            )
        if status == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this resource.", 405
            )
        if status < 500:
            return response.error_response(
                "ERR_INVALID_REQUEST", exc.description or "Bad request.", 422
            )
        return response.error_response("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return response.error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
