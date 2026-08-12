"""Route registration for the /bookstore API."""

from . import (
    clock, terms, publishers, titles, people, sections, adoptions,
    buy_plans, orders, ia_charges, buyback, commissions,
)

_MODULES = (
    clock, terms, publishers, titles, people, sections, adoptions,
    buy_plans, orders, ia_charges, buyback, commissions,
)


def register_all(app):
    for mod in _MODULES:
        app.register_blueprint(mod.bp)
