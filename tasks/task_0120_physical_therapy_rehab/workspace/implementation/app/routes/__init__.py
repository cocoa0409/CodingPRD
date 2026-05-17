"""Blueprint registration."""
from flask import Flask

from .therapists import bp as therapists_bp
from .patients import bp as patients_bp
from .veteran_referrals import bp as veteran_referrals_bp
from .episodes import bp as episodes_bp
from .evaluations import bp as evaluations_bp
from .plan_of_cares import bp as poc_bp
from .authorizations import bp as authorizations_bp
from .visits import bp as visits_bp
from .home_exercise_programs import bp as hep_bp
from .mips import bp as mips_bp
from .discharge import bp as discharge_bp
from .test_infra import bp as test_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(therapists_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(veteran_referrals_bp)
    app.register_blueprint(episodes_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(poc_bp)
    app.register_blueprint(authorizations_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(hep_bp)
    app.register_blueprint(mips_bp)
    app.register_blueprint(discharge_bp)
    app.register_blueprint(test_bp)
