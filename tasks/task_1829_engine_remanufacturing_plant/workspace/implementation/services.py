"""Shared business operations: deposit close, engine sale chain, selectors.

Ledger note (PRD 2.4/2.7/3.1): every mutation of a resource -- including a
cascade write to a parent -- refreshes updated_at and increments version.
Callers bump each affected distributor exactly once per request, regardless of
how many ledger chains of that request touched it.
"""

import calcs
import clock as clockmod
from store import db, stamp_new, touch


def get_or_404(collection, rid):
    from errors import ERR_NOT_FOUND, raise_error

    row = getattr(db, collection).get(rid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "no %s with id %s" % (collection, rid))
    return row


def close_deposit(dep, closed_instant):
    """deposit_refund_calculation against the given close instant.  Stamps
    refunded_cents/forfeited_cents/age_days_at_close/closed_at and moves the
    deposit to CLOSED_REFUNDED (bracket pct > 0) or FORFEITED (pct == 0)."""
    age = clockmod.age_in_days(dep["sold_at"], closed_instant)
    pct, refunded, forfeited = calcs.deposit_refund(dep["amount_cents"], age)
    dep["refunded_cents"] = refunded
    dep["forfeited_cents"] = forfeited
    dep["age_days_at_close"] = age
    dep["closed_at"] = closed_instant
    dep["status"] = "CLOSED_REFUNDED" if pct > 0 else "FORFEITED"
    touch(dep)
    return refunded


def create_deposit(distributor_id, engine_id, spec, sold_instant):
    """SALE/REPLACEMENT CHAIN link 1: a HELD deposit whose amount is copied
    from the spec at sale time."""
    dep = {
        "distributor_id": distributor_id,
        "reman_engine_id": engine_id,
        "amount_cents": spec["core_deposit_cents"],
        "sold_at": sold_instant,
        "status": "HELD",
        "refunded_cents": 0,
        "forfeited_cents": 0,
        "age_days_at_close": None,
        "closed_at": None,
    }
    stamp_new(dep)
    db.core_deposits[dep["id"]] = dep
    return dep


def create_engine(work_order):
    """First entry into ASSEMBLY: the engine is born (BUILT), build spec copied
    from the work order, serial minted 'RMN-' + 6-digit creation sequence."""
    engine = {
        "work_order_id": work_order["id"],
        "build_spec_id": work_order["build_spec_id"],
        "serial_number": db.next_engine_serial(),
        "status": "BUILT",
        "latest_dyno_result": None,
        "sealed_at": None,
        "sealed_by": None,
        "distributor_id": None,
        "sold_at": None,
        "sale_price_cents": None,
    }
    stamp_new(engine)
    db.engines[engine["id"]] = engine
    return engine


def sealed_pool(build_spec_id):
    return [
        e
        for e in db.engines.values()
        if e["status"] == "SEALED" and e["build_spec_id"] == build_spec_id
    ]


def select_sealed_engine(build_spec_id):
    """Server-side allocation: earliest sealed_at, tie-break created_at (then
    insertion order for exact clock ties).  None when the pool is empty."""
    pool = sealed_pool(build_spec_id)
    if not pool:
        return None
    return min(pool, key=lambda e: (e["sealed_at"], e["created_at"], e["_seq"]))


def latest_dyno_test(engine_id):
    """Most recent DynoTest of the engine by created_at (insertion order)."""
    tests = [t for t in db.dyno_tests.values() if t["reman_engine_id"] == engine_id]
    if not tests:
        return None
    return max(tests, key=lambda t: (t["created_at"], t["_seq"]))
