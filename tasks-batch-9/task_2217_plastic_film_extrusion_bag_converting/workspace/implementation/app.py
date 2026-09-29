"""Film Extrusion Bag Converting API — Flask entry point.

Storage is entirely in-memory (see store.py); nothing is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.blend import bp as blend_bp
from routes.converting import bp as converting_bp
from routes.extrusion import bp as extrusion_bp
from routes.printing import bp as printing_bp
from routes.registry import bp as registry_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(registry_bp)
    app.register_blueprint(blend_bp)
    app.register_blueprint(extrusion_bp)
    app.register_blueprint(printing_bp)
    app.register_blueprint(converting_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this route.", 405
            )
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
