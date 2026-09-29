"""Copyright Takedown & Counter-Notice Processing — Flask reference server.

Boots from a completely empty store on every invocation: no entity is seeded and
the logical clock always starts at exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ApiError
from routes_core import core
from routes_notice import clock_bp, notices_bp

API_PREFIX = "/dmca"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:  # Flask >= 2.3 moved the JSON provider settings
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(core, url_prefix=API_PREFIX)
    app.register_blueprint(notices_bp, url_prefix=API_PREFIX)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(error_body(error.error_id, error.message)), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif status < 500:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        return jsonify(error_body(error_id, error.description)), status

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return jsonify(error_body("ERR_INTERNAL", str(error))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
