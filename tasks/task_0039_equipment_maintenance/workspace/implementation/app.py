"""Equipment Maintenance API entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response

from routes.analytics import bp as analytics_bp
from routes.audit import bp as audit_bp
from routes.equipment import bp as equipment_bp
from routes.plans import bp as plans_bp
from routes.requisitions import bp as requisitions_bp
from routes.sites import bp as sites_bp
from routes.spare_parts import bp as spare_parts_bp
from routes.technicians import bp as technicians_bp
from routes.templates import bp as templates_bp
from routes.work_orders import bp as work_orders_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(sites_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(spare_parts_bp)
    app.register_blueprint(technicians_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(requisitions_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(analytics_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_BAD_REQUEST", "Bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(e: HTTPException):
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if e.code == 405:
            return error_response("ERR_NOT_FOUND", "Method not allowed", 404)
        if e.code == 400:
            return error_response("ERR_BAD_REQUEST", e.description or "Bad request", 400)
        return error_response("ERR_BAD_REQUEST", e.description or "Error", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Last-resort: return 400 with a generic envelope so test client doesn't see HTML
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_BAD_REQUEST", str(e) or "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
