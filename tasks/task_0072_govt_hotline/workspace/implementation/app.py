"""Government Hotline API — entry point."""

import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import AppError, ERR_VALIDATION, ERROR_STATUS
import response as resp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(AppError)
    def handle_app_error(e):
        return resp.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Map werkzeug HTTPException to our error envelope. Most often a 404 (no route)
        # or 405 (method not allowed). We surface as ERR_VALIDATION for bad requests
        # except for genuine 404 not-found (no route at all) which we leave as 404.
        code = e.code or 500
        if code == 404:
            return resp.error("ERR_RESOURCE_NOT_FOUND", e.description or "not found", 404)
        if code == 405:
            return resp.error("ERR_VALIDATION", e.description or "method not allowed", 405)
        return resp.error("ERR_VALIDATION", e.description or str(e), code)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return resp.error("ERR_INTERNAL", str(e), 500)

    from routes import register_routes
    register_routes(app)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
