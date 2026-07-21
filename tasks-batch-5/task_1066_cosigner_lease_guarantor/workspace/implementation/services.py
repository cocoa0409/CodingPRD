"""Cross-entity side effects: ledger, cascades, portfolio recompute (PRD 2.4, 3.4-3.8)."""
import db
from calculations import risk_weighted_sum, warn_threshold


ACTIVE_COVERAGE_STATUSES = {"ACTIVE", "RENEWAL_PENDING"}


def append_ledger(guarantee_id, entry_type, amount_cents, direction, balance_after_cents):
    """Append an immutable ledger entry (id + created_at only; PRD 2.4)."""
    entry = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "guarantee_id": guarantee_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "direction": direction,
        "balance_after_cents": balance_after_cents,
        "_seq": db.next_seq(),
    }
    db.ledger_entries[entry["id"]] = entry
    return entry


def terminate_agreements(guarantee_id, from_statuses):
    """Cascade any matching agreements for this guarantee to TERMINATED."""
    for ag in db.agreements.values():
        if ag["guarantee_id"] == guarantee_id and ag["status"] in from_statuses:
            ag["status"] = "TERMINATED"
            db.touch(ag)


def _plan_portfolio_id(plan):
    claim = db.claims.get(plan.get("claim_id"))
    if not claim:
        return None
    guarantee = db.guarantees.get(claim["guarantee_id"])
    if not guarantee:
        return None
    return guarantee.get("portfolio_id")


def recompute_portfolio(portfolio):
    """Rebuild all four aggregates + posture from scratch and record the mutation."""
    pid = portfolio["id"]
    total_active = 0
    weighted_pairs = []
    for g in db.guarantees.values():
        if g.get("portfolio_id") == pid and g["status"] in ACTIVE_COVERAGE_STATUSES:
            total_active += g["total_coverage_cents"]
            weighted_pairs.append((g["remaining_coverage_cents"], g["risk_tier"]))

    total_outstanding = 0
    for rp in db.recovery_plans.values():
        if rp["status"] == "ACTIVE" and _plan_portfolio_id(rp) == pid:
            total_outstanding += rp["outstanding_cents"]

    risk_weighted = risk_weighted_sum(weighted_pairs)
    threshold = warn_threshold(portfolio["exposure_cap_cents"])

    portfolio["total_active_coverage_cents"] = total_active
    portfolio["total_outstanding_recovery_cents"] = total_outstanding
    portfolio["risk_weighted_exposure_cents"] = risk_weighted
    portfolio["posture"] = "RESTRICTED" if risk_weighted >= threshold else "OPEN"
    db.touch(portfolio)


def open_recovery_delta(applicant_id, delta):
    applicant = db.applicants.get(applicant_id)
    if applicant is not None:
        applicant["open_recovery_count"] += delta
        db.touch(applicant)
