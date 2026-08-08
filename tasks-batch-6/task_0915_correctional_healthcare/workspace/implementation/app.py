"""Correctional Healthcare API -- entry point.

Storage is in-memory only (see store.py).  Nothing is seeded at import time or
at startup: the store is empty on every boot.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_RECORD_NOT_FOUND", "resource not found")), 404
        if exc.code == 405:
            return jsonify(error_body("ERR_VALIDATION", "method not allowed")), 400
        return jsonify(error_body("ERR_VALIDATION", exc.description or "bad request")), \
            (exc.code if exc.code and 400 <= exc.code < 500 else 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return jsonify(error_body("ERR_VALIDATION", str(exc))), 400

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False, debug=False)
