"""Register all route blueprints."""
from __future__ import annotations

from flask import Flask


def register_routes(app: Flask) -> None:
    from . import (
        clock as clock_routes,
        parks as park_routes,
        visitors as visitor_routes,
        campgrounds as cg_routes,
        timed_entry as te_routes,
        lottery as lottery_routes,
        backcountry as bc_routes,
    )
    app.register_blueprint(clock_routes.bp)
    app.register_blueprint(park_routes.bp)
    app.register_blueprint(visitor_routes.bp)
    app.register_blueprint(cg_routes.bp)
    app.register_blueprint(te_routes.bp)
    app.register_blueprint(lottery_routes.bp)
    app.register_blueprint(bc_routes.bp)
