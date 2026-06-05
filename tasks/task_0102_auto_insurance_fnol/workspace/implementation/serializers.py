"""Entity -> JSON serializers. Each emits the §2.4 common quartet
(id, created_at, updated_at, version) plus the entity's declared fields.
Internal bookkeeping (_seq) is never exposed.
"""
from util import format_iso


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": format_iso(rec["created_at"]),
        "updated_at": format_iso(rec["updated_at"]),
        "version": rec["version"],
    }


def policy(rec):
    out = _common(rec)
    out.update({
        "policyholder_name": rec["policyholder_name"],
        "policy_number": rec["policy_number"],
        "status": rec["status"],
        "effective_date": format_iso(rec["effective_date"]),
        "expiration_date": format_iso(rec["expiration_date"]),
        "comparative_fault_rule": rec["comparative_fault_rule"],
    })
    return out


def coverage(rec):
    out = _common(rec)
    out.update({
        "policy_id": rec["policy_id"],
        "coverage_type": rec["coverage_type"],
        "limit_cents": rec["limit_cents"],
        "deductible_cents": rec["deductible_cents"],
        "rental_daily_cap_cents": rec["rental_daily_cap_cents"],
        "rental_max_days": rec["rental_max_days"],
    })
    return out


def adjuster(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "license_tier": rec["license_tier"],
        "active": rec["active"],
    })
    return out


def claim(rec):
    out = _common(rec)
    out.update({
        "policy_id": rec["policy_id"],
        "assigned_adjuster_id": rec["assigned_adjuster_id"],
        "loss_datetime": format_iso(rec["loss_datetime"]),
        "loss_type": rec["loss_type"],
        "vehicle_acv_cents": rec["vehicle_acv_cents"],
        "insured_fault_pct": rec["insured_fault_pct"],
        "status": rec["status"],
        "disposition": rec["disposition"],
        "settlement_cents": rec["settlement_cents"],
        "salvage_value_cents": rec["salvage_value_cents"],
        "total_disbursed_cents": rec["total_disbursed_cents"],
    })
    return out


def claim_party(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "party_role": rec["party_role"],
        "display_name": rec["display_name"],
        "fault_pct": rec["fault_pct"],
        "at_fault_carrier_name": rec["at_fault_carrier_name"],
    })
    return out


def coverage_verification(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "matched_coverage_type": rec["matched_coverage_type"],
        "outcome": rec["outcome"],
        "denial_reason": rec["denial_reason"],
    })
    return out


def repair_estimate(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "authored_by_adjuster_id": rec["authored_by_adjuster_id"],
        "lines": rec["lines"],
        "repair_total_cents": rec["repair_total_cents"],
        "status": rec["status"],
    })
    return out


def total_loss_evaluation(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "evaluated_by_adjuster_id": rec["evaluated_by_adjuster_id"],
        "acv_cents": rec["acv_cents"],
        "repair_total_cents": rec["repair_total_cents"],
        "total_loss_ratio": rec["total_loss_ratio"],
        "is_total_loss": rec["is_total_loss"],
        "salvage_retained_by_insurer": rec["salvage_retained_by_insurer"],
    })
    return out


def rental_reimbursement(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "rental_start_date": format_iso(rec["rental_start_date"]),
        "rental_end_date": format_iso(rec["rental_end_date"]),
        "daily_rate_cents": rec["daily_rate_cents"],
        "reimbursable_days": rec["reimbursable_days"],
        "reimbursement_cents": rec["reimbursement_cents"],
        "status": rec["status"],
    })
    return out


def subrogation_case(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "target_party_id": rec["target_party_id"],
        "demand_cents": rec["demand_cents"],
        "recoverable_cents": rec["recoverable_cents"],
        "recovered_cents": rec["recovered_cents"],
        "status": rec["status"],
    })
    return out


def disbursement(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "disbursement_type": rec["disbursement_type"],
        "amount_cents": rec["amount_cents"],
        "source_entity_id": rec["source_entity_id"],
        "status": rec["status"],
    })
    return out
