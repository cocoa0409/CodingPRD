"""Entry point: Flask app, blueprint registration, global error handlers.

Storage is in-memory only (db.store, recreated per process). NO entity seeding at
startup — the store begins empty (except the logical-clock default) and tests build
all state via the declared API surface.
"""

import os

from flask import Flask

from errors import ApiError
import errors
from response import error_response

from routes.admin import bp as admin_bp
from routes.properties import bp as properties_bp
from routes.radon_tests import bp as radon_tests_bp
from routes.mitigation_jobs import bp as mitigation_jobs_bp
from routes.payment_records import bp as payment_records_bp
from routes.permits import bp as permits_bp
from routes.warranties import bp as warranties_bp
from routes.retest_schedules import bp as retest_schedules_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(admin_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(radon_tests_bp)
    app.register_blueprint(mitigation_jobs_bp)
    app.register_blueprint(payment_records_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(warranties_bp)
    app.register_blueprint(retest_schedules_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — no resource exists at this path.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Re-raise ApiError so its dedicated handler runs.
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
