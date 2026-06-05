"""Cross-entity lookups used by route handlers and cascades."""
import db


def coverages_for_policy(policy_id):
    return [c for c in db.coverages.values() if c["policy_id"] == policy_id]


def coverage_of_type(policy_id, coverage_type):
    for c in db.coverages.values():
        if c["policy_id"] == policy_id and c["coverage_type"] == coverage_type:
            return c
    return None


def rental_coverage(policy_id):
    return coverage_of_type(policy_id, "RENTAL")


def matched_coverage_for_claim(claim_rec):
    """The Coverage whose coverage_type == the claim's VERIFIED
    CoverageVerification.matched_coverage_type. Falls back to loss_type when no
    verification is recorded (defensive)."""
    matched_type = latest_verified_matched_type(claim_rec["id"])
    if matched_type is None:
        matched_type = claim_rec["loss_type"]
    return coverage_of_type(claim_rec["policy_id"], matched_type)


def submitted_estimate(claim_id):
    for e in db.repair_estimates.values():
        if e["claim_id"] == claim_id and e["status"] == "SUBMITTED":
            return e
    return None


def submitted_estimates(claim_id):
    return [e for e in db.repair_estimates.values()
            if e["claim_id"] == claim_id and e["status"] == "SUBMITTED"]


def total_loss_evaluations_for_claim(claim_id):
    return [t for t in db.total_loss_evaluations.values()
            if t["claim_id"] == claim_id]


def has_positive_total_loss_eval(claim_id):
    return any(t["is_total_loss"] for t in total_loss_evaluations_for_claim(claim_id))


def latest_total_loss_eval(claim_id):
    rows = total_loss_evaluations_for_claim(claim_id)
    rows.sort(key=lambda r: r.get("_seq", 0))
    return rows[-1] if rows else None


def positive_total_loss_eval(claim_id):
    """The most-recent TotalLossEvaluation with is_total_loss=true, if any."""
    rows = [t for t in total_loss_evaluations_for_claim(claim_id) if t["is_total_loss"]]
    rows.sort(key=lambda r: r.get("_seq", 0))
    return rows[-1] if rows else None


def verifications_for_claim(claim_id):
    """CoverageVerifications still linked to the claim (not cleared by reopen)."""
    return [v for v in db.coverage_verifications.values()
            if v["claim_id"] == claim_id and not v.get("_cleared", False)]


def latest_verified_matched_type(claim_id):
    rows = [v for v in verifications_for_claim(claim_id) if v["outcome"] == "VERIFIED"]
    rows.sort(key=lambda r: r.get("_seq", 0))
    return rows[-1]["matched_coverage_type"] if rows else None


def has_verified_coverage(claim_id):
    return any(v["outcome"] == "VERIFIED" for v in verifications_for_claim(claim_id))


def pending_rentals(claim_id):
    return [r for r in db.rental_reimbursements.values()
            if r["claim_id"] == claim_id and r["status"] == "PENDING"]


def rentals_for_claim(claim_id):
    return [r for r in db.rental_reimbursements.values()
            if r["claim_id"] == claim_id]


def insured_fault_pct(claim_rec):
    return claim_rec["insured_fault_pct"]
