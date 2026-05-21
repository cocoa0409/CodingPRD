from ..store import store
from ..repository import base_internal
from .rider_metrics import recompute_bonus_tier


def create_fine(*, subject_type, subject_id, reason, amount_cents, related_order_id=None,
                related_return_id=None, related_assignment_id=None):
    """Create a fine and apply the numeric ledger debit to the subject.
    Does NOT call touch() on the subject — the caller is responsible for ensuring
    each versioned resource is touched exactly once per request."""
    f = base_internal()
    f.update({
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": reason,
        "amount_cents": int(amount_cents),
        "settlement_status": "PENDING",
        "related_order_id": related_order_id,
        "related_return_id": related_return_id,
        "related_assignment_id": related_assignment_id,
    })
    store.fines[f["id"]] = f
    _apply_ledger(f, sign=-1)
    return f


def waive_fine(f) -> bool:
    if f["settlement_status"] != "PENDING":
        return False
    f["settlement_status"] = "WAIVED"
    _apply_ledger(f, sign=+1)
    return True


def _apply_ledger(f, sign):
    """sign = -1 applies the debit, +1 reverses it. Mutates numeric fields and
    re-derives bonus tier for riders; does NOT touch (no version bump)."""
    subject_type = f["subject_type"]
    subject_id = f["subject_id"]
    amt = f["amount_cents"]
    if subject_type == "RIDER":
        rider = store.riders.get(subject_id)
        if rider is not None:
            rider["wallet_balance_cents"] = rider.get("wallet_balance_cents", 0) + sign * amt
            recompute_bonus_tier(rider)
    elif subject_type == "CUSTOMER":
        c = store.customers.get(subject_id)
        if c is not None:
            new_balance = c.get("credit_balance_cents", 0) + sign * amt
            if new_balance < 0:
                new_balance = 0
            c["credit_balance_cents"] = new_balance
    elif subject_type == "RESTAURANT":
        r = store.restaurants.get(subject_id)
        if r is not None:
            r["pending_settlement_cents"] = r.get("pending_settlement_cents", 0) + sign * amt
