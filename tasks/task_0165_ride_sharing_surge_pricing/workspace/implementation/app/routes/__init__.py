"""Register all blueprint routes."""
from flask import Flask

from .grids import bp as grids_bp
from .drivers import bp as drivers_bp
from .riders import bp as riders_bp
from .rush_hour_windows import bp as rh_bp
from .quest_bonuses import bp as quests_bp
from .airport_queue import bp as queue_bp
from .rides import bp as rides_bp
from .disputes import bp as disputes_bp
from .clock_and_sweep import bp as clock_bp


def register_routes(app: Flask) -> None:
    for bp in (
        grids_bp,
        drivers_bp,
        riders_bp,
        rh_bp,
        quests_bp,
        queue_bp,
        rides_bp,
        disputes_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)
