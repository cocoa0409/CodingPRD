"""Blueprint registration."""

from flask import Blueprint, g, request

from middleware import require_auth
from response import error
from errors import AppError


def register_routes(app):
    @app.before_request
    def _auth_gate():
        # Auth applies to all real API paths. Skip Flask's static endpoint.
        if request.endpoint == "static":
            return None
        require_auth()

    @app.errorhandler(AppError)
    def _handle_app_error(e):
        return error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        # Flask raises 404 only when no route matches; we return a generic
        # not-found envelope.
        return error("ERR_ROUTE_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, AppError):
            return error(e.error_id, e.message, e.http_status)
        # Fall back to a 500 with generic envelope.
        return error("ERR_INTERNAL", str(e), 500)

    from .projects import bp as projects_bp
    from .packages import bp as packages_bp
    from .annotators import bp as annotators_bp
    from .appeals import bp as appeals_bp
    from .payroll import bp as payroll_bp
    from .audit import bp as audit_bp
    from .testing import bp as testing_bp

    app.register_blueprint(projects_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(annotators_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(payroll_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(testing_bp)
