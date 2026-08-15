"""Cross-entity propagation helpers (PRD §2.11).

Every automatic reconciliation is a real mutation on the affected resource:
it refreshes updated_at and increments version (db.touch).
"""

from __future__ import annotations

import db
from constants import CASE_NON_TERMINAL
from services.scoring import bureau_deadline, recompute_pattern_score


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def non_terminal_case_for_claim(claim_id: str):
    for case in db.cases.values():
        if case.get("claim_id") == claim_id and case.get("status") in CASE_NON_TERMINAL:
            return case
    return None


def cases_for_claim(claim_id: str) -> list:
    return [c for c in db.cases.values() if c.get("claim_id") == claim_id]


def active_assignment_for_case(case_id: str):
    for row in db.assignments.values():
        if row.get("case_id") == case_id and row.get("status") == "ACTIVE":
            return row
    return None


def adjust_case_count(investigator_id: str, delta: int) -> None:
    inv = db.investigators.get(investigator_id)
    if inv is None:
        return
    inv["active_case_count"] = max(0, int(inv.get("active_case_count", 0)) + delta)
    db.touch(inv)


# ---------------------------------------------------------------------------
# Claim propagation
# ---------------------------------------------------------------------------


def claim_put_under_review(claim: dict) -> None:
    if claim.get("status") != "UNDER_SIU_REVIEW" or claim.get("payment_hold_reason") != "SIU_INVESTIGATION":
        claim["status"] = "UNDER_SIU_REVIEW"
        claim["payment_hold_reason"] = "SIU_INVESTIGATION"
        db.touch(claim)


def claim_release_to_pending(claim: dict) -> None:
    claim["status"] = "PENDING"
    claim["payment_hold_reason"] = None
    db.touch(claim)


def claim_deny(claim: dict) -> None:
    claim["status"] = "DENIED"
    claim["payment_hold_reason"] = "FRAUD_CONFIRMED"
    db.touch(claim)


def claim_euo_nonappearance(claim: dict) -> None:
    claim["payment_hold_reason"] = "EUO_NONAPPEARANCE"
    claim["status"] = "PAYMENT_DELAYED"
    db.touch(claim)


# ---------------------------------------------------------------------------
# Case closure cascades
# ---------------------------------------------------------------------------


def complete_active_assignment(case: dict) -> None:
    assignment = active_assignment_for_case(case["id"])
    if assignment is None:
        return
    assignment["status"] = "COMPLETED"
    assignment["completed_at"] = db.clock.now_string()
    db.touch(assignment)
    adjust_case_count(assignment.get("investigator_id"), -1)


def auto_create_ledger(case: dict) -> dict:
    ledger = {
        "case_id": case["id"],
        "target_amount_cents": int(case.get("substantiated_fraud_cents", 0)),
        "recovered_amount_cents": 0,
        "outstanding_amount_cents": int(case.get("substantiated_fraud_cents", 0)),
        "status": "OPEN",
    }
    db.stamp_new(ledger)
    db.ledgers[ledger["id"]] = ledger
    return ledger


def auto_create_bureau_referral(case: dict) -> dict:
    claim = db.claims.get(case.get("claim_id")) or {}
    now = db.clock.now
    referral = {
        "case_id": case["id"],
        "state_code": claim.get("state_code"),
        "filed_at": None,
        "deadline_at": db.render_deadline(bureau_deadline(claim.get("state_code"), now)),
        "status": "DRAFT",
        "ack_received_at": None,
        "late_filing": False,
        "_filed_by_user_id": None,
    }
    db.stamp_new(referral)
    db.bureau_referrals[referral["id"]] = referral
    return referral


def link_provider_patterns(case: dict) -> None:
    """A substantiated close links the case into provider patterns (PRD §3.6/§3.8)."""
    for pattern in db.provider_patterns.values():
        linked = pattern.setdefault("linked_case_ids", [])
        if case["id"] not in linked:
            linked.append(case["id"])
        recompute_pattern_score(pattern)
        db.touch(pattern)


# ---------------------------------------------------------------------------
# Ledger reconciliation
# ---------------------------------------------------------------------------


def recompute_ledger(ledger: dict) -> None:
    recovered = sum(
        int(p.get("amount_cents", 0))
        for p in db.payments.values()
        if p.get("ledger_id") == ledger["id"] and p.get("status") == "CLEARED"
    )
    ledger["recovered_amount_cents"] = recovered
    outstanding = int(ledger.get("target_amount_cents", 0)) - recovered
    ledger["outstanding_amount_cents"] = max(0, outstanding)
    status = ledger.get("status")
    if status in ("OPEN", "PARTIALLY_RECOVERED", "FULLY_RECOVERED"):
        if ledger["outstanding_amount_cents"] == 0 and recovered > 0:
            ledger["status"] = "FULLY_RECOVERED"
        elif recovered > 0:
            ledger["status"] = "PARTIALLY_RECOVERED"
        else:
            # A reversal that zeroes the recovered total returns the ledger to OPEN.
            ledger["status"] = "OPEN"
    db.touch(ledger)
