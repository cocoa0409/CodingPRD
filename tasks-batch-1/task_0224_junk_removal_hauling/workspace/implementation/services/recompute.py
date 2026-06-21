"""Derived-field reconciliation: crew.reserved_minutes and customer.outstanding_balance_cents.

Both are recomputed from their source set (never delta-drifted). A recomputation
that changes the value is a mutation of the owning resource: it bumps version and
updated_at (PRD §2.4, §2.5).
"""
from db import db
from models import touch


def recompute_crew_reserved_minutes(crew):
    """Sum window_minutes of this crew's dispatches in {RESERVED, ACTIVE}.

    Bumps crew version/updated_at iff the value changed (PRD §2.5).
    """
    total = 0
    for d in db.dispatches.values():
        if d["crew_id"] == crew["id"] and d["dispatch_status"] in ("RESERVED", "ACTIVE"):
            total += d["window_minutes"]
    if total != crew["reserved_minutes"]:
        crew["reserved_minutes"] = total
        touch(crew)


def recompute_customer_balance(customer):
    """Sum total_cents of this customer's invoices with billing_status == ISSUED.

    Bumps customer version/updated_at iff the value changed (PRD §2.5, §2.9).
    """
    total = 0
    for inv in db.invoices.values():
        if inv["customer_id"] == customer["id"] and inv["billing_status"] == "ISSUED":
            total += inv["total_cents"]
    if total != customer["outstanding_balance_cents"]:
        customer["outstanding_balance_cents"] = total
        touch(customer)
