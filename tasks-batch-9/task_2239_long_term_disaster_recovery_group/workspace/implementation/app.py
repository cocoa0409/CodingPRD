"""Long-Term Disaster Recovery Group API (Flask, in-memory).

Every process boots with completely empty stores and the logical clock pinned to
2026-08-01T00:00:00Z. Nothing is seeded, nothing is persisted.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes.cases import bp as cases_bp
from routes.money import bp as money_bp
from routes.table import bp as table_bp
from routes.work import bp as work_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(cases_bp)
    app.register_blueprint(table_bp)
    app.register_blueprint(money_bp)
    app.register_blueprint(work_bp)

    @app.before_request
    def _serialize_request():
        # The dev server is threaded and every handler mutates shared dicts.
        db.REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release_request(_exc):
        try:
            db.REQUEST_LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "Resource or route does not exist.", 404
            )
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Method is not allowed for this route.", 405
            )
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Request could not be parsed.", 400
            )
        return response.error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return response.error_response("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
