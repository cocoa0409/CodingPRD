"""Shared Office API — Flask application entry point."""
import os
from flask import Flask, jsonify

from errors import APIError
from response import error_response

from routes.system import bp as system_bp
from routes.tenants import bp as tenants_bp
from routes.members import bp as members_bp
from routes.resources import bp as resources_bp
from routes.leases import bp as leases_bp
from routes.reservations import bp as reservations_bp
from routes.visitors import bp as visitors_bp
from routes.badges import bp as badges_bp
from routes.access_events import bp as access_events_bp
from routes.bills import bp as bills_bp


def create_app():
    app = Flask(__name__)

    PREFIX = "/shared-office"

    app.register_blueprint(system_bp, url_prefix=PREFIX)
    app.register_blueprint(tenants_bp, url_prefix=PREFIX)
    app.register_blueprint(members_bp, url_prefix=PREFIX)
    app.register_blueprint(resources_bp, url_prefix=PREFIX)
    app.register_blueprint(leases_bp, url_prefix=PREFIX)
    app.register_blueprint(reservations_bp, url_prefix=PREFIX)
    app.register_blueprint(visitors_bp, url_prefix=PREFIX)
    app.register_blueprint(badges_bp, url_prefix=PREFIX)
    app.register_blueprint(access_events_bp, url_prefix=PREFIX)
    app.register_blueprint(bills_bp, url_prefix=PREFIX)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method Not Allowed", 404)

    @app.errorhandler(500)
    def handle_500(e):
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
