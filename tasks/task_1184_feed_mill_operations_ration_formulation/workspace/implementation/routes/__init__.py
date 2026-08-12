"""Route registration for every (method, path) pair declared in the endpoint table."""
from . import (clock, ingredients, contracts, bins, customers, employees,
               formulas, orders, batches, weighments, samples, flushes,
               lines, trucks, trips)

_MODULES = (clock, ingredients, contracts, bins, customers, employees,
            formulas, orders, batches, weighments, samples, flushes,
            lines, trucks, trips)


def register_routes(app):
    for module in _MODULES:
        app.register_blueprint(module.bp)
