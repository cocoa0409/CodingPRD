"""Route registration."""

from routes import (challenges, clock, cycles, distribution_orders, frameworks,
                    materials, pilots, purchase_orders, quotes, reviews,
                    supplemental)


def register_routes(app):
    for module in (clock, frameworks, cycles, materials, pilots, reviews,
                   quotes, purchase_orders, distribution_orders, supplemental,
                   challenges):
        app.register_blueprint(module.bp)
