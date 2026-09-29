"""District Energy System Operations API.

Boots a completely empty in-memory store on every process start: no seeding,
no preloading, no hardcoded entity data.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response as resp
from errors import ApiError
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        del exc
        return resp.error("ERR_NOT_FOUND", "the requested resource does not exist", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        del exc
        return resp.error("ERR_METHOD_NOT_ALLOWED",
                          "the method is not allowed for this resource", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return resp.error(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return resp.error("ERR_HTTP_%d" % exc.code,
                              exc.description or "request failed", exc.code)
        return resp.error("ERR_INTERNAL", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
