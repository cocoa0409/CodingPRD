"""Medical Examiner Case Management API — entry point.

In-memory storage only; the store is fresh and EMPTY on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes_config import bp as config_bp
from routes_cases import bp as cases_bp
from routes_bodies import bp as bodies_bp
from routes_autopsy import bp as autopsy_bp
from routes_specimens import bp as specimens_bp
from routes_certificates import bp as certificates_bp
from routes_property import bp as property_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(bodies_bp)
    app.register_blueprint(autopsy_bp)
    app.register_blueprint(specimens_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(property_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        code = e.code or 500
        if code == 400:
            return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 400)
        return error_response("ERR_INTERNAL", str(e), code)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
