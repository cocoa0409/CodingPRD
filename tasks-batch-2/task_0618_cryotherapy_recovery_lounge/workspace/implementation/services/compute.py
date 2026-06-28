"""Derived-field reconciliation and the credit-balance rule (PRD §2.6, §3.6).

Per PRD §2.6, whenever the server recomputes a derived field on a resource that
recomputation is a mutation of the owning resource: it refreshes updated_at and
increments version. The two stored-and-reconciled derived fields that follow
this rule explicitly are Member.credit_balance and Subscription.lifetime_paid_cents.

current_cycle_end_at is a pure function of cycle_anchor_at (anchor + 30 days) and
is derived on read, so writing it is not itself a separate mutation.
"""

from clock import parse_iso8601, format_iso8601_ms, add_days
from db import db
from helpers import touch

BILLING_CYCLE_DAYS = 30


# ---------------------------------------------------------------------------
# Subscription.current_cycle_end_at = cycle_anchor_at + 30 days (PRD §2.6).
# ---------------------------------------------------------------------------

def subscription_current_cycle_end_at_dt(sub):
    anchor = parse_iso8601(sub["cycle_anchor_at"])
    return add_days(anchor, BILLING_CYCLE_DAYS)


def subscription_current_cycle_end_at_iso(sub):
    return format_iso8601_ms(subscription_current_cycle_end_at_dt(sub))


# ---------------------------------------------------------------------------
# Subscription.lifetime_paid_cents = sum of amount_cents over its PAID invoices.
# ---------------------------------------------------------------------------

def recompute_lifetime_paid(sub):
    total = sum(
        inv["amount_cents"]
        for inv in db.invoices.values()
        if inv["subscription_id"] == sub["id"] and inv["status"] == "PAID"
    )
    if sub.get("lifetime_paid_cents") != total:
        sub["lifetime_paid_cents"] = total
        touch(sub)
    else:
        sub["lifetime_paid_cents"] = total


# ---------------------------------------------------------------------------
# Member.credit_balance (PRD §3.6): subscription grant when ACTIVE/FROZEN, plus
# the sum of remaining_credits over the member's ACTIVE packs; never negative.
# Recomputing it is a mutation of the member (PRD §2.6).
# ---------------------------------------------------------------------------

def _member_active_subscription(member_id):
    """The member's single live (non-CANCELLED) subscription, if any."""
    for sub in db.subscriptions.values():
        if sub["member_id"] == member_id and sub["status"] != "CANCELLED":
            return sub
    return None


def recompute_credit_balance(member):
    sub = _member_active_subscription(member["id"])
    sub_part = 0
    if sub is not None and sub["status"] in ("ACTIVE", "FROZEN"):
        sub_part = sub["granted_credits_remaining"]
    pack_part = sum(
        pack["remaining_credits"]
        for pack in db.credit_packs.values()
        if pack["member_id"] == member["id"] and pack["status"] == "ACTIVE"
    )
    balance = sub_part + pack_part
    if balance < 0:
        balance = 0
    member["credit_balance"] = balance
    touch(member)


def recompute_credit_balance_by_member_id(member_id):
    member = db.members.get(member_id)
    if member is not None:
        recompute_credit_balance(member)


# ---------------------------------------------------------------------------
# Location.open_booking_count (PRD §2.6): count of this location's BOOKED
# bookings. Maintained incrementally; recompute helper kept for clarity.
# ---------------------------------------------------------------------------

def increment_open_booking_count(location):
    location["open_booking_count"] = location.get("open_booking_count", 0) + 1
    touch(location)


def decrement_open_booking_count(location):
    location["open_booking_count"] = max(0, location.get("open_booking_count", 0) - 1)
    touch(location)
