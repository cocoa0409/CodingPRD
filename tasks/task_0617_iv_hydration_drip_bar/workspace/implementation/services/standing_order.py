"""Standing-order selection for scheduling/approval (PRD §3.3, §3.7).

A drip requiring a standing order needs an ACTIVE StandingOrder covering its
tier in force at start_at: effective_from <= start_at < expires_at (half-open).
Lapse is evaluated lazily before selection.
"""
import db
from helpers import refresh_standing_order


def find_active_for(tier, start_at):
    """Return an in-force ACTIVE standing order for the tier at start_at, or
    None. If multiple match, pick the earliest created (deterministic)."""
    matches = []
    for order in db.standing_orders.values():
        refresh_standing_order(order)
        if order["status"] != "ACTIVE":
            continue
        if order["covered_tier"] != tier:
            continue
        if order["effective_from"] <= start_at < order["expires_at"]:
            matches.append(order)
    if not matches:
        return None
    matches.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return matches[0]
