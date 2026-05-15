"""Exhibition Venue API — entry point.

Listens on the PORT environment variable (default 10000), bound to 0.0.0.0.
"""

import os
import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import db
import clock
from errors import AppError
import response as resp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Test-isolation endpoint — not in PRD, used by benchmark runner to
    # wipe in-memory state and the logical clock between tests.
    @app.route("/__test__/reset", methods=["POST"])
    def __test_reset():
        db.reset_all()
        clock.reset()
        return jsonify({"ok": True}), 200

    # AppError → response envelope
    @app.errorhandler(AppError)
    def _handle_app_error(e):
        return resp.error(e.error_id, e.message, e.http_status)

    # 404 from Flask routing → ERR_NOT_FOUND
    @app.errorhandler(404)
    def _handle_404(e):
        return resp.error("ERR_NOT_FOUND", "Resource not found.", 404)

    # 405 Method Not Allowed → ERR_NOT_FOUND (no separate code in catalog)
    @app.errorhandler(405)
    def _handle_405(e):
        return resp.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def _handle_http(e):
        return resp.error("ERR_INVALID_INPUT", e.description or str(e), e.code or 422)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        app.logger.exception("Unhandled error: %s", e)
        return resp.error("ERR_INTERNAL", str(e), 500)

    from routes import register_routes
    register_routes(app)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", "10000"))
    application = create_app()
    application.run(host="0.0.0.0", port=port, debug=False, threaded=True)
