"""Aggregate route blueprints."""
from flask import Flask

from .organizations import organizations_bp
from .facilities import facilities_bp
from .boundary_changes import boundary_changes_bp
from .reporting_periods import reporting_periods_bp
from .sources import sources_bp
from .factors import factors_bp
from .activity_data import activity_data_bp
from .emission_records import emission_records_bp
from .projects import projects_bp
from .credits import credits_bp
from .reports import reports_bp
from .audit_log import audit_log_bp
from .system import system_bp


def register_all_routes(app: Flask) -> None:
    app.register_blueprint(organizations_bp)
    app.register_blueprint(facilities_bp)
    app.register_blueprint(boundary_changes_bp)
    app.register_blueprint(reporting_periods_bp)
    app.register_blueprint(sources_bp)
    app.register_blueprint(factors_bp)
    app.register_blueprint(activity_data_bp)
    app.register_blueprint(emission_records_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(credits_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(audit_log_bp)
    app.register_blueprint(system_bp)
