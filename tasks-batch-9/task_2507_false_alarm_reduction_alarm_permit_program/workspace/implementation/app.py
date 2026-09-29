"""False Alarm Reduction Permit Program API.

In-memory only: every process start is a clean program with no data at all.
"""

import os
import sys

from flask import Flask, jsonify

from core import _meta
from errors import ApiError
from routes import BLUEPRINTS

API_PREFIX = "/false-alarm-program"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _envelope(error_id, message, status):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return _envelope(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return _envelope("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return _envelope("ERR_RESOURCE_NOT_FOUND",
                         "That method is not routed here.", 404)

    @app.errorhandler(400)
    def _bad_request(exc):
        return _envelope("ERR_INVALID_FIELD_VALUE",
                         "The request body could not be read.", 422)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _envelope(exc.error_id, exc.message, exc.http_status)
        return _envelope("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
