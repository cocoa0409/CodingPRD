"""Game Publishing QA & Platform Certification API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes_core import bp as core_bp
from routes_cert import bp as cert_bp
from routes_release import bp as release_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(core_bp)
    app.register_blueprint(cert_bp)
    app.register_blueprint(release_bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def _generic(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
