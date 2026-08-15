"""Blueprint registration."""

from . import ops, salons, catalog, consultants_routes, orders, shipments, promotions, diversions

BLUEPRINTS = [
    ops.bp,
    salons.bp,
    catalog.bp,
    consultants_routes.bp,
    orders.bp,
    shipments.bp,
    promotions.bp,
    diversions.bp,
]


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
