"""Route registration."""

from routes import (
    castings,
    claims,
    clock,
    customers,
    equipment,
    foundries,
    heats,
    inspections,
    molds,
    orders,
    patterns,
    pour_slots,
    return_lots,
    sand,
    scrap,
)


def register_all(app):
    for mod in (
        clock, foundries, customers, patterns, orders, equipment, heats,
        pour_slots, molds, castings, inspections, scrap, return_lots, sand,
        claims,
    ):
        mod.register(app)
