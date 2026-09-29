"""Individual Artist Fellowship Grants API — Flask entry point.

Storage is in-memory only and every collection starts empty on boot: no
seeding, no preloading, no persistence of any kind.
"""

import os

from flask import Flask

import response
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in routes.blueprints:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route.", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        status = getattr(exc, "code", None)
        if isinstance(status, int) and 400 <= status < 600:
            return response.error(
                "ERR_REQUEST_FAILED", getattr(exc, "description", str(exc)), status
            )
        return response.error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
