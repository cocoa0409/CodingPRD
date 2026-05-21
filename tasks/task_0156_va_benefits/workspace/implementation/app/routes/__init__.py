"""Blueprint registration for the API."""
from __future__ import annotations

from flask import Flask

from .claims import bp as claims_bp
from .dependents import bp as dependents_bp
from .driver import bp as driver_bp
from .enrollments import bp as enrollments_bp
from .schools import bp as schools_bp
from .veterans import bp as veterans_bp
from .voc_rehab import bp as voc_rehab_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(veterans_bp)
    app.register_blueprint(dependents_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(schools_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(voc_rehab_bp)
    app.register_blueprint(driver_bp)
