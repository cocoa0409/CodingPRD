"""Blueprint registration."""
from flask import Flask

from .trials import bp as trials_bp
from .arms import bp as arms_bp
from .consent_versions import bp as cv_bp
from .irb_reviews import bp as irb_bp
from .participants import bp as participants_bp
from .visits import bp as visits_bp
from .adverse_events import bp as ae_bp
from .payments import bp as payments_bp
from .clock_route import bp as clock_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(trials_bp)
    app.register_blueprint(arms_bp)
    app.register_blueprint(cv_bp)
    app.register_blueprint(irb_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(ae_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(clock_bp)
