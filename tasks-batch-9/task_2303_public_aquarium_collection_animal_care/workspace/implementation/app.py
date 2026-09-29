"""Public Aquarium Collection & Animal Care API (in-memory, single process)."""

import os

from flask import Flask

import response
from errors import DEFAULT_MESSAGES, ERROR_STATUS, ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return response.error_response(
            "ERR_VALIDATION", DEFAULT_MESSAGES.get("ERR_VALIDATION", "Malformed request"),
            ERROR_STATUS["ERR_VALIDATION"])

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _internal(exc):  # pragma: no cover - safety net
        if isinstance(exc, ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return response.error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
