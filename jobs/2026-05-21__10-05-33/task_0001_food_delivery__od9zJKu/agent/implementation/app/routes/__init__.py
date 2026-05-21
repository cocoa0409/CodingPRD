"""Aggregates and registers all route blueprints."""
from __future__ import annotations

from flask import Flask


def register_all(app: Flask) -> None:
    from .restaurants import bp as restaurants_bp
    from .menu_items import bp as menu_items_bp
    from .riders import bp as riders_bp
    from .customers import bp as customers_bp
    from .orders import bp as orders_bp
    from .assignments import bp as assignments_bp
    from .returns_routes import bp as returns_bp
    from .fines import bp as fines_bp
    from .work_orders import bp as work_orders_bp
    from .clock_routes import bp as clock_bp

    app.register_blueprint(restaurants_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(riders_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(fines_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(clock_bp)
