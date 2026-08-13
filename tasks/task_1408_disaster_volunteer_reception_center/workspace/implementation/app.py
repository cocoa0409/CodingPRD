"""Entry point: Flask app assembly and error handling.

The in-memory store starts empty on every boot; the logical clock starts at
2026-08-01T00:00:00Z. Nothing is seeded.
"""

import os

from flask import Flask

from errors import ApiError, ERR_RESOURCE_NOT_FOUND
from response import error_response
import routes_core
import routes_vetting
import routes_requests
import routes_field
import routes_hours_risk


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_vetting.bp)
    app.register_blueprint(routes_requests.bp)
    app.register_blueprint(routes_field.bp)
    app.register_blueprint(routes_hours_risk.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_RESOURCE_NOT_FOUND[0], 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_RESOURCE_NOT_FOUND[0], 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
