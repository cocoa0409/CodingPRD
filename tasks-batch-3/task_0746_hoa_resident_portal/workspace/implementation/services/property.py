"""Property derived-field recompute (total_outstanding_cents, fine_balance_cents,
compliance_flag)."""

from datetime import timedelta

import db
from entities import bump
from utils import parse_iso


def recompute(prop, now_iso, now_dt=None):
    """Recompute derived fields on a Property row in place. Bumps version/updated_at
    only if a derived field actually changed."""
    if now_dt is None:
        from clock import get_now
        now_dt = get_now()

    prop_id = prop["id"]
    # total_outstanding_cents = sum(amount_due - amount_paid across OPEN/PARTIALLY_PAID/OVERDUE/DELINQUENT)
    # + sum(fine_balance across FINED/APPEALED/UPHELD)
    outstanding = 0
    fine_balance = 0
    for a in db.assessments.values():
        if a["property_id"] != prop_id:
            continue
        if a["status"] in ("OPEN", "PARTIALLY_PAID", "OVERDUE", "DELINQUENT"):
            unpaid = a["amount_due_cents"] - a["amount_paid_cents"]
            outstanding += unpaid + a.get("late_fee_cents", 0)
    for v in db.violations.values():
        if v["property_id"] != prop_id:
            continue
        if v["status"] in ("FINED", "APPEALED", "UPHELD"):
            fine_balance += v.get("fine_amount_cents", 0)
    outstanding += fine_balance

    compliance = _compute_compliance_flag(prop_id, now_dt)

    changed = False
    if prop.get("total_outstanding_cents") != outstanding:
        prop["total_outstanding_cents"] = outstanding
        changed = True
    if prop.get("fine_balance_cents") != fine_balance:
        prop["fine_balance_cents"] = fine_balance
        changed = True
    if prop.get("compliance_flag") != compliance:
        prop["compliance_flag"] = compliance
        changed = True

    if changed:
        bump(prop, now_iso)


def _compute_compliance_flag(prop_id, now_dt):
    """Fully-derived compliance_flag per PRD §3.1.

    SUSPENDED wins if any Violation on this property has been in an unresolved-fine
    status (FINED/APPEALED/UPHELD) for 60+ days since fined_at.
    Else APPROVED_MOD if any ARCRequest on this property has terminated APPROVED.
    Else OPEN.
    """
    for v in db.violations.values():
        if v["property_id"] != prop_id:
            continue
        if v["status"] not in ("FINED", "APPEALED", "UPHELD"):
            continue
        if not v.get("fined_at"):
            continue
        fined_dt = parse_iso(v["fined_at"])
        if now_dt >= fined_dt + timedelta(days=60):
            return "SUSPENDED"
    for r in db.arc_requests.values():
        if r["property_id"] == prop_id and r["status"] == "APPROVED":
            return "APPROVED_MOD"
    return "OPEN"
