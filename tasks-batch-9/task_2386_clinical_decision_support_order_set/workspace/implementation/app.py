"""Clinical Decision Support Governance API — Flask application entry point.

Storage is in-memory only and completely empty at boot: no seeding, no preloading,
no hardcoded entities.  Every record is created through the declared API surface.
"""
import os

from flask import Flask, g

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    register_routes(app)

    @app.before_request
    def _init_request_state():
        g.touched_records = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(400)
    def _handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_INVALID_REQUEST", "No such route", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
