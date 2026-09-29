"""Vehicle Distribution & Port Processing API — Flask application entrypoint.

The store is entirely in memory and starts empty on every boot, so the harness
may kill and relaunch this process between individual tests.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_INVALID_REQUEST", "The requested path does not exist", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this path", 405
        )

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or exc.name, exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
