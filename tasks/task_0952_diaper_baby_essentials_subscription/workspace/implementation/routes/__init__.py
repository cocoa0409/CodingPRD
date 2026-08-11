"""Route blueprints."""

from routes import (accounts, catalog, children, credits, cycles, gifts, lines,
                    loyalty, ops, refunds, registry, shipments, subs)

BLUEPRINTS = [
    ops.bp,
    accounts.bp,
    children.bp,
    catalog.bp,
    subs.bp,
    cycles.bp,
    lines.bp,
    registry.bp,
    gifts.bp,
    credits.bp,
    shipments.bp,
    loyalty.bp,
    refunds.bp,
]
