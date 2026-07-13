"""Account credit ledger (PRD §2.7) and the rebate engine (PRD §3.5).

Both are pure reconciliations over the account's transactions, so they are
recomputed from the transaction set on every read.  That makes the conserved
invariant `available + outstanding + settled == credit_limit` structurally true
and keeps cascades (void / suspend / confirm) automatically consistent.
"""
from util import dec, round_cents
from services.store import account_transactions


def ledger(account):
    txns = account_transactions(account["id"])
    outstanding = sum(t["gross_amount_cents"] for t in txns
                      if t["posting_status"] in ("AUTHORIZED", "CAPTURED"))
    settled = sum(t["gross_amount_cents"] for t in txns
                  if t["posting_status"] == "SETTLED")
    available = account["credit_limit_cents"] - outstanding - settled
    # Running rebate liability: provisional while CAPTURED, final once SETTLED,
    # nothing at all for AUTHORIZED or VOIDED.
    accrual = 0
    for t in txns:
        if t["posting_status"] == "CAPTURED":
            accrual += t["provisional_rebate_cents"]
        elif t["posting_status"] == "SETTLED":
            accrual += t["final_rebate_cents"]
    return {
        "outstanding_holds_cents": outstanding,
        "settled_spend_cents": settled,
        "available_credit_cents": available,
        "rebate_accrual_cents": accrual,
    }


def hold_amount(txn):
    """gross while AUTHORIZED/CAPTURED, 0 once SETTLED or VOIDED (PRD §3.4)."""
    if txn["posting_status"] in ("AUTHORIZED", "CAPTURED"):
        return txn["gross_amount_cents"]
    return 0


# ---------------------------------------------------------------------------
# Rebate tiers
# ---------------------------------------------------------------------------

def cpg_for(tiers, month_gallons):
    """Highest tier whose min_month_gallons <= month_gallons (threshold inclusive)."""
    ordered = sorted(tiers, key=lambda t: t["min_month_gallons"])
    rate = ordered[0]["cpg_rebate"]
    for tier in ordered:
        if dec(month_gallons) >= dec(tier["min_month_gallons"]):
            rate = tier["cpg_rebate"]
    return rate


def month_gallons(account_id, txn):
    """Sum of gallons over the account's non-VOIDED CAPTURED/SETTLED transactions
    whose purchased_at is in the same UTC calendar month as `txn`.

    Evaluated at capture this yields month-to-date gallons including `txn`
    (the provisional variant); evaluated again at settlement it yields the
    whole-month total (the final variant).
    """
    month = (txn["_purchased_at_dt"].year, txn["_purchased_at_dt"].month)
    total = dec(0)
    for t in account_transactions(account_id):
        if t["posting_status"] not in ("CAPTURED", "SETTLED"):
            continue
        other = t["_purchased_at_dt"]
        if (other.year, other.month) != month:
            continue
        total += dec(t["gallons"])
    return total


def rebate_for(account, txn):
    """Per-transaction rebate, rounded HALF UP per transaction (never sum-then-round)."""
    tiers = account["rebate_tiers"]
    rate = cpg_for(tiers, month_gallons(account["id"], txn))
    return round_cents(dec(txn["gallons"]) * dec(rate))
