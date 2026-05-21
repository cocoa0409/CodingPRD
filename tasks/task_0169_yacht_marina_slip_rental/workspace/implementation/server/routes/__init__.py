"""Route registration — attaches every blueprint to the Flask app."""
from flask import Flask

from .marinas import bp as marinas_bp
from .boaters import bp as boaters_bp
from .vessels import bp as vessels_bp
from .slips import bp as slips_bp
from .reservations import bp as reservations_bp
from .waitlist import bp as waitlist_bp
from .transfers import bp as transfers_bp
from .pump_out import bp as pump_out_bp
from .utility import bp as utility_bp
from .policies import bp as policies_bp
from .tow import bp as tow_bp


def register_blueprints(app: Flask) -> None:
    for bp in (
        marinas_bp,
        boaters_bp,
        vessels_bp,
        slips_bp,
        reservations_bp,
        waitlist_bp,
        transfers_bp,
        pump_out_bp,
        utility_bp,
        policies_bp,
        tow_bp,
    ):
        app.register_blueprint(bp)
