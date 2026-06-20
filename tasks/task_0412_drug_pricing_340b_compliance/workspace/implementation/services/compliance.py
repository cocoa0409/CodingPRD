"""Covered-entity derived gates: compliance_posture and open_repayment_cents.
PRD §2.9."""
from db import db, touch


def recompute_ce_posture(ce):
    """Recompute compliance_posture and open_repayment_cents for a covered
    entity, mutating it (touch) only if a value actually changes.

    FLAGGED when any AuditFinding referencing this CE is OPEN/UNDER_REVIEW/
    DISPUTED, or any RepaymentObligation is OWED/PARTIALLY_PAID. open_repayment_cents
    is the sum of remaining_balance_cents over OWED/PARTIALLY_PAID obligations.
    """
    ce_id = ce["id"]

    has_open_finding = any(
        f["covered_entity_id"] == ce_id
        and f["finding_status"] in ("OPEN", "UNDER_REVIEW", "DISPUTED")
        for f in db.audit_findings.all()
    )

    open_repayment = 0
    has_open_repayment = False
    for r in db.repayment_obligations.all():
        if r["covered_entity_id"] == ce_id and r["status"] in ("OWED", "PARTIALLY_PAID"):
            has_open_repayment = True
            open_repayment += r["remaining_balance_cents"]

    new_posture = "FLAGGED" if (has_open_finding or has_open_repayment) else "GOOD"

    changed = (
        ce["compliance_posture"] != new_posture
        or ce["open_repayment_cents"] != open_repayment
    )
    if changed:
        ce["compliance_posture"] = new_posture
        ce["open_repayment_cents"] = open_repayment
        touch(ce)
