"""DMV Driver Licensing & Road Test API — Flask entry point.

In-memory storage only. The store starts empty on every boot; no seeding.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.clock import bp as clock_bp
from routes.driver_records import bp as driver_records_bp
from routes.examiners import bp as examiners_bp
from routes.knowledge_tests import bp as knowledge_tests_bp
from routes.road_tests import bp as road_tests_bp
from routes.licenses import bp as licenses_bp
from routes.violations import bp as violations_bp
from routes.suspensions import bp as suspensions_bp
from routes.cdl import bp as cdl_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(driver_records_bp)
    app.register_blueprint(examiners_bp)
    app.register_blueprint(knowledge_tests_bp)
    app.register_blueprint(road_tests_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(suspensions_bp)
    app.register_blueprint(cdl_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found"), 404

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed"), 404

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request"), 400
        return error_response("ERR_INVALID_REQUEST", str(e)), e.code or 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Internal error"), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
