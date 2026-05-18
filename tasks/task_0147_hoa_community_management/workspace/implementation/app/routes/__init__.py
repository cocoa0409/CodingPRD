"""Register all blueprint routes."""
from flask import Flask

from .acc import bp as acc_bp
from .assessments import bp as assessments_bp
from .board import bp as board_bp
from .clock import bp as clock_bp
from .elections import bp as elections_bp
from .liens import bp as liens_bp
from .members import bp as members_bp
from .payments import bp as payments_bp
from .reserve_studies import bp as reserve_bp
from .units import bp as units_bp
from .violations import bp as violations_bp


def register_routes(app: Flask) -> None:
    for bp in (
        units_bp,
        members_bp,
        assessments_bp,
        payments_bp,
        acc_bp,
        violations_bp,
        board_bp,
        elections_bp,
        liens_bp,
        reserve_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)
