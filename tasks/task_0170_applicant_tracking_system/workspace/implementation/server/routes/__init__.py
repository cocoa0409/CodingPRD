"""Route blueprint registry."""
from flask import Flask

from .admin import admin_bp
from .applications import applications_bp
from .background_checks import background_checks_bp
from .candidates import candidates_bp
from .diversity_goals import diversity_goals_bp
from .hiring_managers import hiring_managers_bp
from .interviewers import interviewers_bp
from .interviews import interviews_bp
from .offers import offers_bp
from .recruiters import recruiters_bp
from .referral_bonuses import referral_bonuses_bp
from .requisitions import requisitions_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(recruiters_bp)
    app.register_blueprint(hiring_managers_bp)
    app.register_blueprint(interviewers_bp)
    app.register_blueprint(candidates_bp)
    app.register_blueprint(requisitions_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(background_checks_bp)
    app.register_blueprint(referral_bonuses_bp)
    app.register_blueprint(diversity_goals_bp)
    app.register_blueprint(admin_bp)
