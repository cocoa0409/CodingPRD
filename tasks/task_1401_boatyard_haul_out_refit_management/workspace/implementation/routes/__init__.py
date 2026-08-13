from flask import Blueprint

from . import (
    vessels,
    insurance,
    jobs,
    lift_slots,
    yard,
    work_orders,
    parts,
    compliance,
    ledger,
    ops,
)

ALL_BLUEPRINTS = [
    vessels.bp,
    insurance.bp,
    jobs.bp,
    lift_slots.bp,
    yard.bp,
    work_orders.bp,
    parts.bp,
    compliance.bp,
    ledger.bp,
    ops.bp,
]


def register_routes(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
