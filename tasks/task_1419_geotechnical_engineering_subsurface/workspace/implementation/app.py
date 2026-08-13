"""Geotechnical Subsurface API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os

from flask import Flask

from errors import ApiError, err
from response import error_response
from routes_closeout import bp as closeout_bp
from routes_core import bp as core_bp
from routes_field import bp as field_bp
from routes_lab import bp as lab_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(core_bp)
    app.register_blueprint(field_bp)
    app.register_blueprint(lab_bp)
    app.register_blueprint(closeout_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_RESOURCE_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_RESOURCE_NOT_FOUND", "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(err("ERR_VALIDATION", "Malformed request: %s" % e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
