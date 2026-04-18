import os
from flask import Flask, request, g

from errors import APIError, raise_error, ERR_MISSING_AUTH, ERR_UNKNOWN_ROLE
from response import success, error as error_response
from middleware import authenticate


def create_app() -> Flask:
    app = Flask(__name__)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def _handle_400(e):
        return error_response("ERR_PAGINATION_OUT_OF_RANGE", str(e), 400)

    @app.errorhandler(Exception)
    def _handle_generic(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(e), 500)

    @app.before_request
    def _auth_and_ctx():
        # Skip auth for health check
        if request.path == "/shared-office/health":
            return None
        if not request.path.startswith("/shared-office"):
            return None
        authenticate()

    # Register blueprints
    from routes.health import bp as health_bp
    from routes.clock import bp as clock_bp
    from routes.tenants import bp as tenants_bp
    from routes.leases import bp as leases_bp
    from routes.members import bp as members_bp
    from routes.resources import bp as resources_bp
    from routes.reservations import bp as reservations_bp
    from routes.visitors import bp as visitors_bp
    from routes.access_badges import bp as badges_bp
    from routes.access_events import bp as events_bp
    from routes.bills import bp as bills_bp

    app.register_blueprint(health_bp, url_prefix="/shared-office")
    app.register_blueprint(clock_bp, url_prefix="/shared-office")
    app.register_blueprint(tenants_bp, url_prefix="/shared-office")
    app.register_blueprint(leases_bp, url_prefix="/shared-office")
    app.register_blueprint(members_bp, url_prefix="/shared-office")
    app.register_blueprint(resources_bp, url_prefix="/shared-office")
    app.register_blueprint(reservations_bp, url_prefix="/shared-office")
    app.register_blueprint(visitors_bp, url_prefix="/shared-office")
    app.register_blueprint(badges_bp, url_prefix="/shared-office")
    app.register_blueprint(events_bp, url_prefix="/shared-office")
    app.register_blueprint(bills_bp, url_prefix="/shared-office")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
