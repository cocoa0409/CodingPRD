"""Transfer of Development Rights program API (Flask, in-memory)."""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
from routes.areas import bp as areas_bp
from routes.certificates import bp as certificates_bp
from routes.easements import bp as easements_bp
from routes.market import bp as market_bp
from routes.ops import bp as ops_bp
from routes.parcels import bp as parcels_bp
from routes.parties import bp as parties_bp
from routes.receiving import bp as receiving_bp

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        parties_bp,
        areas_bp,
        parcels_bp,
        easements_bp,
        certificates_bp,
        market_bp,
        receiving_bp,
        ops_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _serialize_requests():
        _LOCK.acquire()

    @app.teardown_request
    def _release_requests(exc):
        try:
            _LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return respond_error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_NOT_FOUND", 404, "resource not found")
        if exc.code == 405:
            return respond_error("ERR_INVALID_REQUEST", 405, "method not allowed")
        if exc.code == 400:
            return respond_error("ERR_INVALID_REQUEST", 400, "malformed request")
        return respond_error("ERR_INVALID_REQUEST", exc.code or 500, exc.description or "request failed")

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return respond_error("ERR_INTERNAL", 500, str(exc))

    return app


application = create_app()

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
