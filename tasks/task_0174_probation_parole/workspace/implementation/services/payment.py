"""Payment waterfall allocation (PRD §3.6)."""
import clock
import db
from calculations import outstanding_now
from errors import ApiError, ERR_PAYMENT_EXCEEDS_BALANCE
from services.common import recompute_balances

TYPE_RANK = {"RESTITUTION": 0, "FEE": 1}


def _ordered_obligations(supervisee, allocation_policy):
    """Return the supervisee's OPEN/PARTIALLY_PAID obligations in waterfall order.

    Tie-break is created_at ASC (with insertion-seq stabilizer); the obligation
    id is NEVER used. parent_obligation_id ASC is the final tie-break, with None
    sorting before any string.
    """
    obs = [
        o
        for o in db.obligations.values()
        if o.get("supervisee_id") == supervisee["id"]
        and o["status"] in ("OPEN", "PARTIALLY_PAID")
    ]

    def parent_key(o):
        p = o.get("parent_obligation_id")
        # None sorts first.
        return (0, "") if p is None else (1, p)

    if allocation_policy == "RESTITUTION_FIRST":
        key = lambda o: (
            TYPE_RANK[o["obligation_type"]],
            o["created_at"],
            o.get("_seq", 0),
            parent_key(o),
        )
    else:  # OLDEST_FIRST
        key = lambda o: (
            o["created_at"],
            o.get("_seq", 0),
            TYPE_RANK[o["obligation_type"]],
            parent_key(o),
        )
    return sorted(obs, key=key)


def total_outstanding(supervisee):
    """Total currently-outstanding across OPEN/PARTIALLY_PAID obligations,
    measured chronologically (no future projection)."""
    now = clock.now()
    total = 0
    for o in db.obligations.values():
        if o.get("supervisee_id") != supervisee["id"]:
            continue
        if o["status"] not in ("OPEN", "PARTIALLY_PAID"):
            continue
        total += outstanding_now(o, now)
    return total


def apply_payment(supervisee, amount_cents, allocation_policy):
    """Allocate a payment across obligations; returns (applied_breakdown).

    Overpayment is rejected whole before any post (ERR_PAYMENT_EXCEEDS_BALANCE).
    """
    # Reject overpayment before posting anything.
    if amount_cents > total_outstanding(supervisee):
        raise ApiError(*ERR_PAYMENT_EXCEEDS_BALANCE, "Payment exceeds outstanding balance.")

    now = clock.now()
    ordered = _ordered_obligations(supervisee, allocation_policy)
    remaining = amount_cents
    applied = {}
    for ob in ordered:
        if remaining <= 0:
            break
        outstanding = outstanding_now(ob, now)
        take = min(remaining, max(outstanding, 0))
        if take <= 0:
            continue
        applied[ob["id"]] = take
        ob["paid_cents"] += take
        remaining -= take
        # Update obligation status.
        new_outstanding = outstanding_now(ob, now)
        if new_outstanding <= 0:
            ob["status"] = "PAID"
        else:
            ob["status"] = "PARTIALLY_PAID"
        db.touch(ob)

    # Recompute supervisee posted balances after allocation.
    if recompute_balances(supervisee):
        db.touch(supervisee)
    return applied
