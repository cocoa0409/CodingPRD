"""Junior Golf Tour Ranking Administration API.

Flask entry point. All state lives in process memory (see store.py) and the
store starts empty on every boot: nothing is seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, ERROR_STATUS, DEFAULT_MESSAGE
import routes_cases
import routes_core
import routes_entries
import routes_rounds
import routes_tournaments


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_tournaments.bp)
    app.register_blueprint(routes_entries.bp)
    app.register_blueprint(routes_rounds.bp)
    app.register_blueprint(routes_cases.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif exc.code in (400, 415):
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        status = ERROR_STATUS.get(error_id, exc.code or 500)
        if error_id in ("ERR_NOT_FOUND", "ERR_METHOD_NOT_ALLOWED"):
            status = exc.code
        message = DEFAULT_MESSAGE.get(error_id) or (exc.description or "Request failed")
        return error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
