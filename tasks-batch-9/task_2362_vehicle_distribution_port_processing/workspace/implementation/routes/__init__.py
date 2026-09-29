"""Blueprint registry."""
from routes import (
    berths,
    centers,
    claims,
    clock,
    holds,
    inspections,
    kits,
    parties,
    release_orders,
    repairs,
    surveys,
    vehicles,
    vessels,
    work_orders,
)

BLUEPRINTS = [
    clock.bp,
    centers.bp,
    berths.bp,
    vessels.bp,
    vehicles.bp,
    surveys.bp,
    claims.bp,
    repairs.bp,
    kits.bp,
    work_orders.bp,
    inspections.bp,
    holds.bp,
    parties.bp,
    release_orders.bp,
]


def register_routes(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    return app
