"""Loan creation shared by desk checkout and hold fulfilment (PRD §3.3, §3.6)."""

import clock
import db
from timeutil import add_days
from services import derive


def create_loan(copy, patron, branch):
    """Create an ACTIVE loan on `copy` for `patron`, set the copy ON_LOAN, and
    reconcile derived counters. Caller is responsible for all precondition checks
    (copy AVAILABLE / on hold shelf, card, block, limits)."""
    now = clock.now()
    loan = {
        "copy_id": copy["id"],
        "patron_id": patron["id"],
        "status": "ACTIVE",
        "checked_out_at": now,
        "due_date": add_days(now, branch["loan_period_days"]),
        "renewal_count": 0,
        "returned_at": None,
        "accrued_fine_cents": 0,
    }
    db.stamp_create(loan)
    db.loans[loan["id"]] = loan

    copy["status"] = "ON_LOAN"
    db.touch(copy)

    derive.reconcile_title_by_id(copy["title_id"])
    derive.reconcile_patron(patron)
    return loan
