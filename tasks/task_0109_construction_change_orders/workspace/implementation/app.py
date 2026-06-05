"""Construction Change Orders API — Flask entry point.

In-memory only. The store starts empty on every boot; no seeding. The harness
restarts this process before every test, so module-load must inject no state.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.projects import bp as projects_bp
from routes.sov_lines import bp as sov_lines_bp
from routes.change_orders import bp as change_orders_bp
from routes.pay_applications import bp as pay_applications_bp
from routes.commitments import bp as commitments_bp
from routes.rfis import bp as rfis_bp
from routes.submittals import bp as submittals_bp
from routes.lien_waivers import bp as lien_waivers_bp
from routes.punch_items import bp as punch_items_bp
from routes.inspection_windows import bp as inspection_windows_bp
from routes.retention_releases import bp as retention_releases_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(projects_bp)
    app.register_blueprint(sov_lines_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(pay_applications_bp)
    app.register_blueprint(commitments_bp)
    app.register_blueprint(rfis_bp)
    app.register_blueprint(submittals_bp)
    app.register_blueprint(lien_waivers_bp)
    app.register_blueprint(punch_items_bp)
    app.register_blueprint(inspection_windows_bp)
    app.register_blueprint(retention_releases_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route — surface as ERR_NOT_FOUND in the standard envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        # Defensive: never leak a stack trace; report as a generic 422 invalid
        # request so the envelope stays consistent.
        return error_response("ERR_INVALID_REQUEST", "Invalid request: %s" % exc, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
