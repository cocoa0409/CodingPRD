"""Cascading transitions (PRD §2.10, §3). Every derived mutation refreshes
updated_at and bumps version on the affected resource."""
from db import store, touch


def release_reservation(visit):
    """Covered visit cancelled / no-show before completion: release the counter."""
    if visit["coverage"] != "SUBSCRIPTION_COVERED" or not visit["subscription_id"]:
        return
    sub = store.subscriptions.get(visit["subscription_id"])
    if sub is None:
        return
    if visit["visit_type"] == "COOP_CLEANING":
        sub["used_cleanings"] = max(0, sub["used_cleanings"] - 1)
    elif visit["visit_type"] == "FLOCK_HEALTH_CHECK":
        sub["used_health_checks"] = max(0, sub["used_health_checks"] - 1)
    touch(sub)


def revert_orders_for_visit(visit):
    """Each visit cancellation reverts linked PLACED orders to DRAFT and unlinks."""
    for o in store.orders.values():
        if o["fulfillment_visit_id"] == visit["id"] and o["status"] == "PLACED":
            o["status"] = "DRAFT"
            o["fulfillment_visit_id"] = None
            touch(o)


def cancel_visit_cascade(visit):
    """ServiceVisit -> CANCELLED with reservation release and order reversion."""
    visit["status"] = "CANCELLED"
    touch(visit)
    release_reservation(visit)
    revert_orders_for_visit(visit)


def cancel_covered_visits(subscription):
    """Covered pending visits of this subscription -> CANCELLED (cascade link 2)."""
    visits = sorted(store.visits.values(), key=lambda v: v["_seq"])
    for v in visits:
        if (
            v["subscription_id"] == subscription["id"]
            and v["coverage"] == "SUBSCRIPTION_COVERED"
            and v["status"] in ("REQUESTED", "SCHEDULED", "RESCHEDULE_REQUESTED")
        ):
            v["status"] = "CANCELLED"
            touch(v)
            if v["visit_type"] == "COOP_CLEANING":
                subscription["used_cleanings"] = max(0, subscription["used_cleanings"] - 1)
            elif v["visit_type"] == "FLOCK_HEALTH_CHECK":
                subscription["used_health_checks"] = max(0, subscription["used_health_checks"] - 1)
            revert_orders_for_visit(v)


def pause_subscription(subscription):
    """Subscription ACTIVE -> PAUSED with the two-link covered-visit cascade."""
    subscription["status"] = "PAUSED"
    cancel_covered_visits(subscription)
    touch(subscription)


def suspend_household(household):
    """HouseholdAccount ACTIVE -> SUSPENDED, cascading into the subscription."""
    household["status"] = "SUSPENDED"
    touch(household)
    subs = sorted(store.subscriptions.values(), key=lambda s: s["_seq"])
    for sub in subs:
        if sub["household_id"] == household["id"] and sub["status"] == "ACTIVE":
            pause_subscription(sub)
