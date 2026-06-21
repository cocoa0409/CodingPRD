"""Owner standing score (PRD §3.9, scaffold calculations.owner_standing_score).

base = min(60, floor(max(0, balance) / OVERDUE_UNIT_CENTS) * POINTS_PER_UNIT)
penalty = min(40, open_unpaid * UNPAID_INVOICE_POINTS)
score = min(100, base + penalty)

committed variant: balance = Owner.account_balance_cents; counts only FINALIZED
  invoices whose paid_amount_cents < amount_due_cents. Written to standing_score;
  drives status (DELINQUENT when score >= SUSPEND_SCORE else ACTIVE).
provisional variant: balance = account_balance_cents PLUS projected amount_due of
  every OPEN invoice; OPEN invoices also count toward open_unpaid. Read-only.
"""
from db import db
from services.common import touch

OVERDUE_UNIT_CENTS = 10000
POINTS_PER_UNIT = 10
UNPAID_INVOICE_POINTS = 20
SUSPEND_SCORE = 80


def _score(balance, open_unpaid):
    base = min(60, (max(0, balance) // OVERDUE_UNIT_CENTS) * POINTS_PER_UNIT)
    penalty = min(40, open_unpaid * UNPAID_INVOICE_POINTS)
    return min(100, base + penalty)


def recompute_committed(owner):
    """Final variant — written to standing_score after finalize/void/pay; derives
    status; counts as a mutation of the owner (touch)."""
    balance = owner["account_balance_cents"]
    open_unpaid = 0
    for inv in db.invoices.values():
        if inv["owner_id"] != owner["id"]:
            continue
        if inv["status"] == "FINALIZED" and inv["paid_amount_cents"] < inv["amount_due_cents"]:
            open_unpaid += 1
    score = _score(balance, open_unpaid)
    owner["standing_score"] = score
    owner["status"] = "DELINQUENT" if score >= SUSPEND_SCORE else "ACTIVE"
    touch(owner)


def compute_provisional(owner):
    """Provisional projection — written to provisional_standing_score on owner read.
    Adds the projected amount_due of every OPEN invoice to balance, and counts those
    OPEN invoices toward the unpaid penalty. Returns the projected score (caller sets
    the field and touches)."""
    from services.invoicing import project_open_invoice_amount_due
    balance = owner["account_balance_cents"]
    open_unpaid = 0
    for inv in db.invoices.values():
        if inv["owner_id"] != owner["id"]:
            continue
        if inv["status"] == "OPEN":
            balance += project_open_invoice_amount_due(owner, inv)
            open_unpaid += 1
    return _score(balance, open_unpaid)
