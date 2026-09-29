"""Work-Based Learning & Student Internship Placement API.

In-memory only: every boot starts with empty collections and the logical clock
at the PRD's fixed default of 2026-08-01T00:00:00Z.
"""

import os
import sys

from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import error_body  # noqa: E402
from routes import BLUEPRINTS  # noqa: E402

API_PREFIX = "/wbl"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(400)
    def _bad_request(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "The request is malformed.")), 400

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The requested route does not exist.")), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The HTTP method is not allowed on this route.")), 405

    @app.errorhandler(415)
    def _unsupported_media(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The request body must be JSON.")), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
        app.logger.exception("unhandled error: %s", exc)
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
