"""Route registration — collects all blueprints and attaches them to the app."""
from flask import Flask

from .riders import bp as riders_bp
from .employers import bp as employers_bp
from .cards import bp as cards_bp
from .certificates import bp as certificates_bp
from .low_income import bp as low_income_bp
from .mobile_tokens import bp as mobile_tokens_bp
from .trips import bp as trips_bp
from .cap_periods import bp as cap_periods_bp
from .fsa import bp as fsa_bp
from .disputes import bp as disputes_bp
from .admin import bp as admin_bp


def register_blueprints(app: Flask) -> None:
    for bp in (
        riders_bp,
        employers_bp,
        cards_bp,
        certificates_bp,
        low_income_bp,
        mobile_tokens_bp,
        trips_bp,
        cap_periods_bp,
        fsa_bp,
        disputes_bp,
        admin_bp,
    ):
        app.register_blueprint(bp)
