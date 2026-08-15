"""Corporate Entity Governance API — Flask entry point.

Mounts all route blueprints, registers the error-envelope handlers, and runs
the server on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response, ok_object  # noqa: F401 (ok_object re-exported)
import response as response_mod

import routes_misc
import routes_entities
import routes_appointments
import routes_resolutions
import routes_filings
import routes_qualifications
import routes_grants
import routes_certificates
import routes_ownership


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    app.register_blueprint(routes_misc.bp)
    app.register_blueprint(routes_entities.bp)
    app.register_blueprint(routes_appointments.bp)
    app.register_blueprint(routes_resolutions.bp)
    app.register_blueprint(routes_filings.bp)
    app.register_blueprint(routes_qualifications.bp)
    app.register_blueprint(routes_grants.bp)
    app.register_blueprint(routes_certificates.bp)
    app.register_blueprint(routes_ownership.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405,
                                       "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
