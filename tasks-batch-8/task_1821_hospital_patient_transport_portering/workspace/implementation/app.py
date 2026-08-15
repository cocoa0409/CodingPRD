"""Hospital Patient Transport API — entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot and
the logical clock starts at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    from routes.config import bp as config_bp
    from routes.requests import bp as requests_bp
    from routes.cleaning import bp as cleaning_bp
    from routes.admin import bp as admin_bp

    app.register_blueprint(config_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(cleaning_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_NOT_FOUND", 405, "method not allowed"))

    @app.errorhandler(500)
    def handle_internal(err):
        return error_response(ApiError("ERR_INTERNAL", 500, "internal server error"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
