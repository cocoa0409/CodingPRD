"""Catastrophe Response Claim Surge Staffing API.

Flat URL topology: every route is exactly the path declared in the PRD, with no
common prefix.  All state lives in process memory (see store.py), so relaunching
this process discards every byte of prior state.  Nothing is ever seeded.
"""
import os

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError

import routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    routes.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        # No catalogue identifier covers an unrouted path.
        return jsonify(error_body("ERR_NOT_FOUND", "Unknown route.")), 404

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")), 405

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
        return jsonify(error_body("ERR_INTERNAL", str(exc))), 500

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=False, debug=False,
                    use_reloader=False)
