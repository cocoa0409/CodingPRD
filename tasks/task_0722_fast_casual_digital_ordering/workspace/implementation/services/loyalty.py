"""Loyalty account / points ledger projections (PRD §2.10)."""
from db import db
from response import now_iso

GOLD_FLOOR = 5000
PLATINUM_FLOOR = 15000


def tier_for(lifetime):
    if lifetime >= PLATINUM_FLOOR:
        return "PLATINUM"
    if lifetime >= GOLD_FLOOR:
        return "GOLD"
    return "GREEN"


def append_ledger_entry(loyalty_account_id, delta_points, reason, order_id=None):
    """Append an immutable ledger entry and recompute account projections."""
    ts = now_iso()
    entry = {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": next(db._seq),
        "loyalty_account_id": loyalty_account_id,
        "order_id": order_id,
        "delta_points": delta_points,
        "reason": reason,
    }
    db.points_ledger_entries[entry["id"]] = entry
    recompute_account(loyalty_account_id)
    return entry


def recompute_account(loyalty_account_id):
    """points_balance = sum(delta); lifetime = sum(positive delta); tier derived.

    Recomputation is a mutation of the account (bump version, refresh updated_at).
    """
    acct = db.loyalty_accounts[loyalty_account_id]
    balance = 0
    lifetime = 0
    for e in db.points_ledger_entries.values():
        if e["loyalty_account_id"] == loyalty_account_id:
            balance += e["delta_points"]
            if e["delta_points"] > 0:
                lifetime += e["delta_points"]
    acct["points_balance"] = balance
    acct["lifetime_points_earned"] = lifetime
    acct["tier"] = tier_for(lifetime)
    db.touch(acct)


def account_for_customer(customer_id):
    for acct in db.loyalty_accounts.values():
        if acct["customer_id"] == customer_id:
            return acct
    return None
