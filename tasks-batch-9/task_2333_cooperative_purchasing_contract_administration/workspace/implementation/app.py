"""Cooperative Purchasing Contract Administration API.

Flask application factory and entry point.  All state lives in process-local
dictionaries (see ``db.py``); the store is empty on every boot, so relaunching
the process is a full reset.
"""

import os

from flask import Flask, jsonify

import middleware
from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - Flask < 2.2
        pass

    @app.before_request
    def _begin():
        middleware.begin_request()

    register_routes(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "request does not conform to the endpoint schema",
                              400)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_NOT_FOUND", "the requested path does not exist",
                              404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "the method is not allowed for this path", 405)

    @app.errorhandler(Exception)
    def _internal(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "internal server error", 500)

    @app.route("/health", methods=["GET"])
    def _health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
