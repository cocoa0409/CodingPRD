"""Blueprint registration."""

from flask import request

import db
from middleware import require_auth, require_role
from response import error, success
from errors import AppError
from config import ROLE_ADMIN


def register_routes(app):
    @app.before_request
    def _auth_gate():
        if request.endpoint == "static":
            return None
        require_auth()

    @app.post("/_test/reset")
    def _test_reset():
        """Test-only hook (not in PRD §4): wipe in-memory state."""
        require_role(ROLE_ADMIN)
        db.reset_all()
        return success({}, 200)

    @app.errorhandler(AppError)
    def _handle_app_error(e):
        return error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error("ERR_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, AppError):
            return error(e.error_id, e.message, e.http_status)
        return error("ERR_INTERNAL", str(e), 500)

    from .patients import bp as patients_bp
    from .doctors import bp as doctors_bp
    from .pharmacists import bp as pharmacists_bp
    from .department_mappings import bp as dm_bp
    from .triage import bp as triage_bp
    from .consultations import bp as consultations_bp
    from .prescriptions import bp as prescriptions_bp
    from .insurance import bp as insurance_bp
    from .followup import bp as followup_bp
    from .audit import bp as audit_bp
    from .system import bp as system_bp

    app.register_blueprint(patients_bp)
    app.register_blueprint(doctors_bp)
    app.register_blueprint(pharmacists_bp)
    app.register_blueprint(dm_bp)
    app.register_blueprint(triage_bp)
    app.register_blueprint(consultations_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(followup_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(system_bp)
