"""Development Impact Fee Study & Nexus Analysis service (Flask, in-memory)."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError, api_error
from routes import applications, clock_routes, fund, programs, studies


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(programs.bp)
    app.register_blueprint(studies.bp)
    app.register_blueprint(applications.bp)
    app.register_blueprint(fund.bp)
    app.register_blueprint(clock_routes.bp)

    @app.before_request
    def _acquire():
        db.lock.acquire()

    @app.teardown_request
    def _release(_exception=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code in (400, 415):
            return response.error_response(api_error("ERR_INVALID_REQUEST"))
        return response.error_response(
            ApiError("ERR_HTTP_ERROR", error.code or 500, error.description or "Request failed."))

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", error)
        return response.error_response(
            ApiError("ERR_INTERNAL", 500, "Internal server error."))

    return app


application = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
