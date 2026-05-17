"""Blueprint registration."""
from flask import Flask

from .clinicians import bp as clinicians_bp
from .clock_routes import bp as clock_bp
from .episodes import bp as episodes_bp
from .mileage import bp as mileage_bp
from .oasis import bp as oasis_bp
from .patients import bp as patients_bp
from .sweep import bp as sweep_bp
from .visits import bp as visits_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(patients_bp)
    app.register_blueprint(clinicians_bp)
    app.register_blueprint(oasis_bp)
    app.register_blueprint(episodes_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(mileage_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(sweep_bp)
