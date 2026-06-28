"""Member strike accounting and suspension (PRD §2.9, scaffold
member_active_strike_count)."""
from datetime import timedelta

from clock import clock
from db import db, touch
from constants import STRIKE_WINDOW_DAYS, STRIKE_SUSPEND_THRESHOLD


def active_strike_count(member_id):
    """Count PenaltyCharge rows for the member that count as a strike, are not
    waived, and whose charge time falls within the trailing STRIKE_WINDOW_DAYS
    window ending at the current logical-clock instant (inclusive on both
    bounds). PRD §2.9."""
    now = clock.now()
    window_start = now - timedelta(days=STRIKE_WINDOW_DAYS)
    count = 0
    for p in db.penalty_charges.values():
        if p["member_id"] != member_id:
            continue
        if not p["counts_as_strike"] or p["waived"]:
            continue
        if window_start <= p["charged_at"] <= now:
            count += 1
    return count


def apply_strike_suspension(member):
    """After a new strike-bearing charge, recompute active_strike_count and, if
    it reaches the threshold (>=), move ACTIVE -> SUSPENDED. PRD §2.9.

    Returns True if the member was suspended by this call."""
    if member["account_status"] != "ACTIVE":
        return False
    if active_strike_count(member["id"]) >= STRIKE_SUSPEND_THRESHOLD:
        member["account_status"] = "SUSPENDED"
        touch(member)
        return True
    return False
