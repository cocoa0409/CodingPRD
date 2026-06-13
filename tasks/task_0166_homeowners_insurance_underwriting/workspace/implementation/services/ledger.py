"""Per-policy append-only premium ledger (PRD §2.8, §1.3 premium_balance).

premium_balance = sum(DEBIT) - sum(CREDIT). Recomputed after every posting.
"""
from decimal import Decimal

from db import db
from services.calc import to_money
from services.models import touch


def _ledger(policy_id):
    return db.ledgers.setdefault(policy_id, [])


def post(policy, posting_type, amount, reason):
    """Append a DEBIT/CREDIT posting and recompute the policy's premium_balance.

    Recomputing premium_balance counts as a mutation of the policy (PRD §2.4):
    it refreshes updated_at and increments version.
    """
    assert posting_type in ("DEBIT", "CREDIT")
    _ledger(policy["id"]).append(
        {"type": posting_type, "amount": to_money(amount), "reason": reason}
    )
    recompute_balance(policy)


def recompute_balance(policy):
    total = Decimal("0")
    for p in _ledger(policy["id"]):
        if p["type"] == "DEBIT":
            total += p["amount"]
        else:
            total -= p["amount"]
    policy["premium_balance"] = to_money(total)
    touch(policy)
