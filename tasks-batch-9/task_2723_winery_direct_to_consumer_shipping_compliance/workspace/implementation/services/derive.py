"""Derived counters on Winery, Consumer and ClubSubscription (PRD 2.10).

These are never supplied by a client and never incrementally patched on faith:
they are recomputed from the rows that moved. Version bumps are performed
explicitly at the documented events, not here.
"""
from store import db, touch
from services import volume


def winery_orders(winery_id):
    return [o for o in db.orders.values() if o["winery_id"] == winery_id]


def winery_derived(winery):
    wid = winery["id"]
    accrued = 0
    reversed_cents = 0
    order_ids = set()
    for order in db.orders.values():
        if order["winery_id"] != wid:
            continue
        order_ids.add(order["id"])
        if order.get("_has_cleared_once"):
            accrued += order["excise_tax_cents"]
        reversed_cents += order.get("excise_reversed_cents") or 0
    suspended = 0
    for sub in db.club_subscriptions.values():
        if sub["winery_id"] == wid and sub["status"] == "SUSPENDED_COMPLIANCE":
            suspended += 1
    open_exceptions = 0
    for exc in db.compliance_exceptions.values():
        if exc["status"] == "OPEN" and exc["order_id"] in order_ids:
            open_exceptions += 1
    return {
        "excise_accrued_cents": accrued,
        "excise_reversed_cents": reversed_cents,
        "suspended_subscription_count": suspended,
        "open_exception_count": open_exceptions,
    }


def subscription_derived(sub):
    consumed = 0
    for order in db.orders.values():
        if order.get("club_subscription_id") == sub["id"] and order.get("_has_cleared_once"):
            consumed += 1
    remaining = sub["annual_allotment"] - consumed
    if remaining < 0:
        remaining = 0
    return {"consumed_shipments": consumed, "remaining_allotment": remaining}


def remaining_allotment(sub):
    return subscription_derived(sub)["remaining_allotment"]


def bump_consumer(consumer):
    """A derived recompute counts as a mutation of the Consumer row (PRD 2.5)."""
    touch(consumer)


def bump_winery(winery):
    touch(winery)


def consumer_derived(consumer):
    return volume.consumer_derived(consumer)


def screening_tier(consumer):
    return volume.consumer_derived(consumer)["screening_tier"]
