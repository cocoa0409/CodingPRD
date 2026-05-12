"""Blueprint registration and global error handlers."""

from flask import request

from errors import (
    AppError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_DEFECT_NOT_FOUND,
)
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
        return error("ERR_NOT_FOUND_ROUTE", "Route not found.", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error(ERR_INSUFFICIENT_PERMISSIONS, "Method not allowed.", 403)

    @app.errorhandler(400)
    def _handle_400(e):
        return error(ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, AppError):
            return error(e.error_id, e.message, e.http_status)
        return error("ERR_INTERNAL", str(e), 500)

    from .projects import bp as projects_bp
    from .modules import bp as modules_bp
    from .team_members import bp as team_members_bp
    from .defects import bp as defects_bp
    from .attachments import bp as attachments_bp
    from .duplicate_links import bp as duplicate_links_bp
    from .severity_overrides import bp as severity_overrides_bp
    from .regression_runs import bp as regression_runs_bp
    from .audit import bp as audit_bp
    from .statistics import bp as statistics_bp
    from .system import bp as system_bp

    app.register_blueprint(projects_bp)
    app.register_blueprint(modules_bp)
    app.register_blueprint(team_members_bp)
    app.register_blueprint(defects_bp)
    app.register_blueprint(attachments_bp)
    app.register_blueprint(duplicate_links_bp)
    app.register_blueprint(severity_overrides_bp)
    app.register_blueprint(regression_runs_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(statistics_bp)
    app.register_blueprint(system_bp)
