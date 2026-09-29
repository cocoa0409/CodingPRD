"""Barge Line & Inland Waterway Freight API.

Storage is in-memory only and starts completely empty on every boot; no entity
is ever seeded, preloaded or hardcoded at startup.
"""
import logging
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response
import routes_contract
import routes_harbor
import routes_lock
import routes_reference
import routes_tow


def create_app():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_harbor.bp)
    app.register_blueprint(routes_lock.bp)
    app.register_blueprint(routes_tow.bp)
    app.register_blueprint(routes_contract.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_INVALID_REQUEST", "Unknown resource path."))
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed."))
        if err.code == 400:
            return error_response(ApiError("ERR_INVALID_REQUEST", "Malformed request."))
        return error_response(ApiError("ERR_INVALID_REQUEST", err.description or "Request failed."))

    @app.errorhandler(Exception)
    def _unhandled(err):
        app.logger.exception("unhandled error")
        body = {
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
