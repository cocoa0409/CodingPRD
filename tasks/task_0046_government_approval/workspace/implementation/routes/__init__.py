"""Blueprint registration and global error handlers."""

from flask import request

from errors import AppError, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_VALIDATION_FAILED
from middleware import require_auth
from response import error


def register_routes(app):
    @app.before_request
    def _auth_gate():
        if request.endpoint == "static":
            return None
        require_auth()

    @app.errorhandler(AppError)
    def _handle_app_error(e):
        return error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error(ERR_NOT_FOUND, "Route not found.", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error(ERR_FORBIDDEN, "Method not allowed.", 403)

    @app.errorhandler(400)
    def _handle_400(e):
        return error(ERR_VALIDATION_FAILED, "Bad request.", 422)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, AppError):
            return error(e.error_id, e.message, e.http_status)
        # Catch-all so leaked exceptions still produce envelope.
        return error("ERR_INTERNAL", str(e), 500)

    from .departments import bp as departments_bp
    from .matters import bp as matters_bp
    from .material_templates import bp as material_templates_bp
    from .certificate_templates import bp as certificate_templates_bp
    from .applications import bp as applications_bp
    from .review_tasks import bp as review_tasks_bp
    from .certificates import bp as certificates_bp
    from .events_audit import bp as events_audit_bp
    from .testing import bp as testing_bp
    from .reports import bp as reports_bp

    app.register_blueprint(departments_bp)
    app.register_blueprint(matters_bp)
    app.register_blueprint(material_templates_bp)
    app.register_blueprint(certificate_templates_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(review_tasks_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(events_audit_bp)
    app.register_blueprint(testing_bp)
    app.register_blueprint(reports_bp)
