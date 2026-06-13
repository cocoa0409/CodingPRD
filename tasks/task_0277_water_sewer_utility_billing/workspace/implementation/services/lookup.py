"""Existence lookups (PRD §2.8) — raise ERR_NOT_FOUND when absent."""
import db
import errors


def _get(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found.")
    return rec


def rate_schedule(rid):
    return _get(db.rate_schedules, rid)


def account(rid):
    return _get(db.accounts, rid)


def meter(rid):
    return _get(db.meters, rid)


def billing_cycle(rid):
    return _get(db.billing_cycles, rid)


def bill(rid):
    return _get(db.bills, rid)


def budget_plan(rid):
    return _get(db.budget_plans, rid)


def assistance_enrollment(rid):
    return _get(db.assistance_enrollments, rid)


def leak_adjustment(rid):
    return _get(db.leak_adjustments, rid)


def shutoff_order(rid):
    return _get(db.shutoff_orders, rid)
