"""Loss-ratio evaluation (scaffold calculation loss_ratio; PRD section 3.8).

Threshold comparisons use the ROUNDED ratios and are inclusive (>=). Only the
incurred basis drives outcomes; the paid basis is informational.
"""
from db import STORE
from services.pricing import evaluation_earned_cents, ratio_pct

EARNED_POLICY_STATUSES = ("ISSUED", "PENDING_CANCELLATION", "CANCELLED", "EXPIRED")
PAID_CLAIM_STATUSES = ("PAID", "CLOSED")
OPEN_CLAIM_STATUSES = ("REPORTED", "UNDER_REVIEW", "REFERRED", "APPROVED", "REOPENED")


def evaluate_program(program, clock):
    """Returns dict with earned_premium_cents, paid_losses_cents,
    case_reserves_cents, paid_loss_ratio_pct (Decimal|None),
    incurred_loss_ratio_pct (Decimal|None), outcome."""
    pid = program["id"]
    earned = 0
    for p in STORE.policies.values():
        if p["program_id"] == pid and p["status"] in EARNED_POLICY_STATUSES:
            earned += evaluation_earned_cents(p, clock)
    paid = 0
    reserves = 0
    for c in STORE.claims.values():
        if c["program_id"] != pid:
            continue
        if c["status"] in PAID_CLAIM_STATUSES and c["paid_at"] is not None and c["paid_at"] <= clock:
            paid += c["paid_cents"]
        if c["status"] in OPEN_CLAIM_STATUSES:
            reserves += c["case_reserve_cents"]
    paid_ratio = ratio_pct(paid, earned)
    incurred_ratio = ratio_pct(paid + reserves, earned)
    if earned < program["min_earned_premium_for_ratio_cents"]:
        outcome = "INSUFFICIENT_DATA"
    elif incurred_ratio is not None and incurred_ratio >= program["termination_threshold_pct"]:
        outcome = "TERMINATION_REVIEW"
    elif incurred_ratio is not None and incurred_ratio >= program["corrective_threshold_pct"]:
        outcome = "CORRECTIVE_ACTION"
    else:
        outcome = "OK"
    return {
        "earned_premium_cents": earned,
        "paid_losses_cents": paid,
        "case_reserves_cents": reserves,
        "paid_loss_ratio_pct": paid_ratio,
        "incurred_loss_ratio_pct": incurred_ratio,
        "outcome": outcome,
    }
