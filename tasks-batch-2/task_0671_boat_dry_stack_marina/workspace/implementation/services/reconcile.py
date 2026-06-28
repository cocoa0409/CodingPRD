"""Derived/computed field recomputation (PRD §3.1, §3.7).

- account_balance_cents: sum of owner's ISSUED invoice amounts (>= 0).
- total_rack_count: count of racks for a marina.
- priority_score: waitlist ranking at read time.
"""
from db import db
from clock import clock
from services.calculations import compute_waitlist_priority, DELINQUENCY_THRESHOLD_CENTS
from clock import parse_iso


def account_balance(owner_id):
    """Sum of amount_cents for this owner's invoices with status == ISSUED.
    PAID and VOIDED excluded. Never below zero."""
    total = 0
    for inv in db.invoices.values():
        if inv["owner_id"] == owner_id and inv["status"] == "ISSUED":
            total += inv["amount_cents"]
    return max(total, 0)


def total_rack_count(marina_id):
    return sum(1 for r in db.racks.values() if r["marina_id"] == marina_id)


def waitlist_priority_at_read(entry):
    """Recompute priority_score against the logical clock at read time."""
    joined_at_dt = parse_iso(entry["joined_at"])
    return compute_waitlist_priority(entry, clock.now(), joined_at_dt)
