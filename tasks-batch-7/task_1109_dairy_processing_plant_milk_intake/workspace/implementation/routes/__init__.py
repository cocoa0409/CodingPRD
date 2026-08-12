"""Blueprint registration."""
from routes import (
    clock_routes,
    dist_routes,
    haulers,
    permits,
    pools,
    producers,
    receipts,
    runs,
    settlements,
)

_ALL = (
    clock_routes.bp,
    producers.bp,
    haulers.bp,
    receipts.bp,
    settlements.bp,
    runs.bp,
    dist_routes.bp,
    permits.bp,
    pools.bp,
)


def register_routes(app):
    for blueprint in _ALL:
        app.register_blueprint(blueprint)
