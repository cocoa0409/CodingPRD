"""Outbound Contact Compliance API — Flask application entry point.

Storage is entirely in-memory and starts empty on every process launch: no
seeding, no preloading, no persistence between runs.
"""

import os

from flask import Flask

from errors import ApiError
from response import error
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error("ERR_INVALID_REQUEST", "No route matches that path.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error("ERR_INVALID_REQUEST", "That method is not allowed on this path.", 405)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
