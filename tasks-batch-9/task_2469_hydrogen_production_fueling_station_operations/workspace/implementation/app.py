"""Hydrogen Fueling Ops API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot: no seeding,
no preloading, no persistence to disk.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response, respond
from errors import ApiError
from routes import config, dispensing, incentives, logistics, production, safety, uptime
from store import db


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (config, production, logistics, dispensing, safety, incentives, uptime):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(_exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        status = err.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        else:
            error_id = "ERR_INVALID_REQUEST"
        return respond(
            {"error_id": error_id, "message": err.description or "Request failed."},
            "error",
            status,
        )

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover
        return respond(
            {"error_id": "ERR_INTERNAL", "message": str(err)},
            "error",
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
