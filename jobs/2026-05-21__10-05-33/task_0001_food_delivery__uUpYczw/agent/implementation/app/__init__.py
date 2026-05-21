"""Flask app factory — wires middleware, error handlers, and route blueprints."""
from flask import Flask

from .envelope import install_envelope_handlers
from .store import Store
from .clock import Clock


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # singleton state for in-memory persistence
    app.config["STORE"] = Store()
    app.config["CLOCK"] = Clock()

    install_envelope_handlers(app)

    # register route blueprints
    from .routes import (
        restaurants,
        menu_items,
        riders,
        customers,
        orders,
        assignments,
        returns_routes,
        fines,
        work_orders,
        clock_routes,
    )

    app.register_blueprint(restaurants.bp)
    app.register_blueprint(menu_items.bp)
    app.register_blueprint(riders.bp)
    app.register_blueprint(customers.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(assignments.bp)
    app.register_blueprint(returns_routes.bp)
    app.register_blueprint(fines.bp)
    app.register_blueprint(work_orders.bp)
    app.register_blueprint(clock_routes.bp)

    return app
