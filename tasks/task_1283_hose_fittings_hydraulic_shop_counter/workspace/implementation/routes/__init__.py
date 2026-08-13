"""Route registration for the /api API."""

from . import (
    clock, customers, assets, inspections, reels, couplings, orders,
    dispatches,
)

_MODULES = (
    clock, customers, assets, inspections, reels, couplings, orders,
    dispatches,
)


def register_all(app):
    for mod in _MODULES:
        app.register_blueprint(mod.bp)
