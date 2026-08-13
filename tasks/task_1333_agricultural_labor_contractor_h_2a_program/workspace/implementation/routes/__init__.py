from . import audit, core, housing, orders, people, transfers, work

ALL_BLUEPRINTS = [
    core.bp,
    orders.bp,
    people.bp,
    housing.bp,
    work.bp,
    transfers.bp,
    audit.bp,
]
