"""Fix-and-Flip Hard Money Lending API -- Flask application factory and entrypoint.

State lives entirely in process memory (core.Store) and starts empty on every
boot; there is no persistence layer of any kind.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify

from core import ApiError, error_response, _meta  # noqa: E402
from routes.draws import bp as draws_bp  # noqa: E402
from routes.origination import bp as origination_bp  # noqa: E402
from routes.servicing import bp as servicing_bp, clock_bp  # noqa: E402

API_PREFIX = "/lending"


def _plain_error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(origination_bp, url_prefix=API_PREFIX)
    app.register_blueprint(draws_bp, url_prefix=API_PREFIX)
    app.register_blueprint(servicing_bp, url_prefix=API_PREFIX)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return _plain_error("ERR_NOT_FOUND", 404, "No such route.")

    @app.errorhandler(405)
    def _handle_405(_err):
        return _plain_error("ERR_METHOD_NOT_ALLOWED", 405,
                            "The HTTP method is not allowed for this route.")

    @app.errorhandler(400)
    def _handle_400(_err):
        return _plain_error("ERR_INVALID_REQUEST", 400,
                            "The request body or query parameters are malformed.")

    @app.errorhandler(Exception)
    def _handle_500(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error: %s", err)
        return _plain_error("ERR_INTERNAL", 500, "Internal server error.")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
