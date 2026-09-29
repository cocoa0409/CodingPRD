"""Blueprint registration for every route module."""

from routes import (
    adjustments,
    claims,
    food,
    monitoring,
    ops,
    peer_groups,
    price_ceilings,
    price_cycles,
    price_submissions,
    sanctions,
    vendors,
)

BLUEPRINTS = (
    peer_groups.bp,
    food.bp,
    vendors.bp,
    price_cycles.bp,
    price_submissions.bp,
    price_ceilings.bp,
    monitoring.bp,
    claims.bp,
    adjustments.bp,
    sanctions.bp,
    ops.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
