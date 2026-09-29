"""Corporate Archives & Heritage Program API.

In-memory Flask application.  The store is empty on every boot: no entity is
seeded, preloaded or hardcoded -- every record is created by clients through
the declared endpoints.
"""

import os

from flask import Flask, g

from errors import ApiError
from response import error_response
from routes.access import bp as access_bp
from routes.config import bp as config_bp
from routes.custody import bp as custody_bp
from routes.deaccession import bp as deaccession_bp
from routes.heritage import bp as heritage_bp
from routes.preservation import bp as preservation_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        config_bp,
        custody_bp,
        preservation_bp,
        access_bp,
        heritage_bp,
        deaccession_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _reset_touch_set():
        g._touched = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(_exc):
        return error_response("ERR_INVALID_REQUEST", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(_exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(400)
    def _handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
