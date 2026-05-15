"""Aggregate all blueprints and register them with the Flask app."""
from __future__ import annotations

from flask import Flask

from .core_enterprises import bp as core_enterprises_bp
from .suppliers import bp as suppliers_bp
from .payable_confirmations import bp as payable_confirmations_bp
from .receivables import bp as receivables_bp
from .verifications import bp as verifications_bp
from .financing_applications import bp as financing_applications_bp
from .disbursements import bp as disbursements_bp
from .repayment_schedules import bp as repayment_schedules_bp
from .collection_cases import bp as collection_cases_bp
from .audit_logs import bp as audit_logs_bp
from .admin import bp as admin_bp


def register_all_routes(app: Flask) -> None:
    app.register_blueprint(core_enterprises_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(payable_confirmations_bp)
    app.register_blueprint(receivables_bp)
    app.register_blueprint(verifications_bp)
    app.register_blueprint(financing_applications_bp)
    app.register_blueprint(disbursements_bp)
    app.register_blueprint(repayment_schedules_bp)
    app.register_blueprint(collection_cases_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(admin_bp)
