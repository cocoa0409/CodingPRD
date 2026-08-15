"""Entry point: Flask app assembly, error handlers, route registration.

The store starts empty on every boot — no entity is seeded, preloaded, or
hardcoded at startup. Tests construct all preconditions via the API surface.
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response

from routes.registration import bp as registration_bp
from routes.applications import bp as applications_bp
from routes.audits import bp as audits_bp
from routes.nonconformities import bp as nonconformities_bp
from routes.certificates import bp as certificates_bp
from routes.scope_changes_appeals import bp as scope_changes_appeals_bp

API_PREFIX = "/certification-body"


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    app.register_blueprint(registration_bp, url_prefix=API_PREFIX)
    app.register_blueprint(applications_bp, url_prefix=API_PREFIX)
    app.register_blueprint(audits_bp, url_prefix=API_PREFIX)
    app.register_blueprint(nonconformities_bp, url_prefix=API_PREFIX)
    app.register_blueprint(certificates_bp, url_prefix=API_PREFIX)
    app.register_blueprint(scope_changes_appeals_bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(
            ERR_INVALID_REQUEST, "The requested resource does not exist", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(
            ERR_INVALID_REQUEST, "Method not allowed on this resource", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive catch-all
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        app.logger.exception("Unexpected error: %s", err)
        return error_response(ERR_INVALID_REQUEST, "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
