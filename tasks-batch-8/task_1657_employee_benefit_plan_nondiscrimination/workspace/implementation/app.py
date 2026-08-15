"""Benefit Plan Nondiscrimination API — Flask entry point.

Mounts all /ndt route blueprints, installs the error handlers producing the
standard error envelope, and runs the server on 0.0.0.0:$PORT (default 10000).
The store is in-memory only and starts empty on every boot; no seeding.
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes.census import bp as census_bp
from routes.safe_harbor import bp as safe_harbor_bp
from routes.structure import bp as structure_bp
from routes.testing import bp as testing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(structure_bp)
    app.register_blueprint(census_bp)
    app.register_blueprint(testing_bp)
    app.register_blueprint(safe_harbor_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, 400, "Malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ERR_INVALID_REQUEST, 400,
                              "Unexpected error: %s" % type(err).__name__)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
