"""Escrow Holdback Administration API — entry point.

Storage is in-memory only (module-level dicts) and starts empty on every
boot; the logical clock defaults to 2026-08-01T00:00:00Z and never falls
back to wall-clock time.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import bp
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        return error_response("ERR_VALIDATION", err.description, err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % err, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
