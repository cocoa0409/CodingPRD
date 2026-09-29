"""Correspondent Mortgage Purchase API -- Flask application factory."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError

from routes.catalog import catalog_bp
from routes.sellers import sellers_bp
from routes.commitments import commitments_bp
from routes.loans import loans_bp
from routes.repurchase import repurchase_bp

API_PREFIX = "/correspondent"


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp, url_prefix=API_PREFIX)
    app.register_blueprint(sellers_bp, url_prefix=API_PREFIX)
    app.register_blueprint(commitments_bp, url_prefix=API_PREFIX)
    app.register_blueprint(loans_bp, url_prefix=API_PREFIX)
    app.register_blueprint(repurchase_bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request body is invalid.", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
