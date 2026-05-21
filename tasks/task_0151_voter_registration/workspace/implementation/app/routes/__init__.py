"""Register all blueprint routes."""
from flask import Flask

from .absentee import bp as absentee_bp
from .ballots import bp as ballots_bp
from .clock import bp as clock_bp
from .curing import bp as curing_bp
from .elections import bp as elections_bp
from .machines import bp as machines_bp
from .precincts import bp as precincts_bp
from .recounts import bp as recounts_bp
from .test_reset import bp as test_reset_bp
from .voters import bp as voters_bp


def register_routes(app: Flask) -> None:
    for bp in (
        clock_bp,
        elections_bp,
        precincts_bp,
        voters_bp,
        absentee_bp,
        curing_bp,
        ballots_bp,
        machines_bp,
        recounts_bp,
        test_reset_bp,
    ):
        app.register_blueprint(bp)
