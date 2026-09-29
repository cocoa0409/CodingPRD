"""Water Utility High-Bill Investigation & Leak Adjustment API.

Flask application factory + entry point.  All state lives in process memory and
starts completely empty on every boot -- nothing is seeded or preloaded.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_a
import routes_b
import routes_c
import routes_d


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)
    app.register_blueprint(routes_d.bp)

    @app.before_request
    def _init_request():
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_INVALID_REQUEST", "resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "method not allowed for this resource", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "resource not found", 404)
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "method not allowed for this resource", 405
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "bad request", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
