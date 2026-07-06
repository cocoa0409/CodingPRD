"""Domain helpers shared across routes: derived-counter maintenance, scoring,
and the validation/reversal settlement cascades (PRD 3.5, 3.6, 3.8, 3.9).
"""
from db import db, stamp_create, touch, new_id, parse_iso
import calc


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def get_scorecard_for_assignment(assignment_id):
    for sc in db.scorecards.values():
        if sc["assignment_id"] == assignment_id:
            return sc
    return None


def evidence_for_assignment(assignment_id):
    return [e for e in db.evidence.values() if e["assignment_id"] == assignment_id]


def reimbursement_for_assignment(assignment_id):
    for r in db.reimbursements.values():
        if r["assignment_id"] == assignment_id:
            return r
    return None


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def flagged_sections(assignment_id, weights_json):
    """Sections (keys of weights_json) that have at least one FLAGGED evidence
    item tagged to them (PRD 3.6 audited score)."""
    flagged = set()
    for e in evidence_for_assignment(assignment_id):
        if e["review_status"] == "FLAGGED" and e.get("section_key") in weights_json:
            flagged.add(e["section_key"])
    return flagged


def compute_estimated_score(assignment, script, scorecard):
    return calc.weighted_score(
        script["weights_json"], scorecard["section_scores_json"], flagged_sections=None
    )


def compute_audited_score(assignment, script, scorecard):
    flagged = flagged_sections(assignment["id"], script["weights_json"])
    return calc.weighted_score(
        script["weights_json"], scorecard["section_scores_json"], flagged_sections=flagged
    )


# --------------------------------------------------------------------------- #
# Reimbursement computations
# --------------------------------------------------------------------------- #
def provisional_reimbursable(assignment, script):
    oop = assignment["claimed_out_of_pocket_cents"]
    return calc.reimbursable(assignment["travel_distance_km"], oop, script["reimburse_cap_cents"])


def final_oop_cents(assignment_id):
    total = 0
    for e in evidence_for_assignment(assignment_id):
        if e["kind"] == "RECEIPT" and e["review_status"] == "APPROVED":
            total += e["receipt_amount_cents"]
    return total


def final_reimbursable(assignment, script):
    oop = final_oop_cents(assignment["id"])
    return calc.reimbursable(assignment["travel_distance_km"], oop, script["reimburse_cap_cents"])


# --------------------------------------------------------------------------- #
# Derived counters
# --------------------------------------------------------------------------- #
def recompute_client_billable(wave):
    """Full recompute from scratch (PRD 3.6 / calc client_billable)."""
    client = db.clients[wave["client_id"]]
    validated = [
        a for a in db.assignments.values()
        if a["wave_id"] == wave["id"] and a["status"] == "VALIDATED"
    ]
    wave["validated_shop_count"] = len(validated)
    wave["client_billable_cents"] = len(validated) * client["fee_per_completed_shop_cents"]
    touch(wave)


def adjust_open_assignment_count(shopper, delta):
    shopper["open_assignment_count"] = shopper["open_assignment_count"] + delta
    touch(shopper)


def adjust_reliability(shopper, delta, floor=0, cap=100):
    new_val = shopper["reliability_score"] + delta
    if new_val < floor:
        new_val = floor
    if new_val > cap:
        new_val = cap
    shopper["reliability_score"] = new_val
    touch(shopper)


# --------------------------------------------------------------------------- #
# Settlement cascade (used by validate and by the rejection-appeal cascade)
# --------------------------------------------------------------------------- #
def settle_validation(assignment, script, shopper, wave, scorecard, validated_by_user_id):
    """Compute final figures, set VALIDATED, create the ACCRUED reimbursement,
    bump wave counters. Shared by SUBMITTED->VALIDATED (PRD 3.6) and the
    REJECTION_APPEAL overturn cascade (PRD 3.8)."""
    # Audited score + audit_status.
    scorecard["audited_score"] = compute_audited_score(assignment, script, scorecard)
    scorecard["audit_status"] = "AUDITED"
    touch(scorecard)

    # Final reimbursement + shopper fee.
    assignment["reimbursable_cents"] = final_reimbursable(assignment, script)
    assignment["shopper_fee_cents"] = calc.shopper_fee(
        script["base_fee_cents"], shopper["reliability_score"]
    )
    assignment["status"] = "VALIDATED"
    assignment["validated_by_user_id"] = validated_by_user_id
    touch(assignment)

    # Reimbursement (ACCRUED).
    reimb = {
        "assignment_id": assignment["id"],
        "shopper_id": shopper["id"],
        "amount_cents": assignment["reimbursable_cents"] + assignment["shopper_fee_cents"],
        "status": "ACCRUED",
        "payout_batch_id": None,
    }
    stamp_create(reimb)
    db.reimbursements[reimb["id"]] = reimb

    # Wave counters.
    recompute_client_billable(wave)
    return reimb


def reverse_reimbursement(reimb):
    """ACCRUED -> REVERSED side effect; decrement wave counter (PRD 3.9)."""
    reimb["status"] = "REVERSED"
    touch(reimb)
    assignment = db.assignments[reimb["assignment_id"]]
    wave = db.waves[assignment["wave_id"]]
    recompute_client_billable(wave)
