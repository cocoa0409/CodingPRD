"""Flask application entry point.

Storage is in-memory only and the process starts with every collection empty:
nothing is seeded, preloaded or registered at boot.  The harness relaunches this
process before each test, so a fresh boot is always a fresh, empty world.
"""

import os

from flask import Flask, jsonify

from core import _meta, error_response
from errors import ApiError
from views import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error)

    @app.errorhandler(404)
    def handle_not_found(_error):
        return _envelope("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return _envelope(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return error_response(error)
        return _envelope("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


def _envelope(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
