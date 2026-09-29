"""Row -> JSON projection for every entity.

Monetary and acreage Decimals are emitted as JSON numbers; point counters stay
integers. Four operator/inspector figures are derived on read rather than
stored, so they can never drift from the rows they summarise.
"""

import calculations as calc
from db import fmt_ts


def _num(value):
    if value is None:
        return None
    return float(value)


def _common(row, data):
    data["id"] = row["id"]
    data["created_at"] = fmt_ts(row["created_at"])
    data["updated_at"] = fmt_ts(row["updated_at"])
    data["version"] = row["version"]
    return data


def operator_out(row):
    return _common(
        row,
        {
            "legal_name": row["legal_name"],
            "tangible_net_worth": _num(row["tangible_net_worth"]),
            "fixed_assets_in_state": _num(row["fixed_assets_in_state"]),
            "total_liabilities": _num(row["total_liabilities"]),
            "net_income_prior_year": _num(row["net_income_prior_year"]),
            "elected_financial_test": row["elected_financial_test"],
            "registry_status": row["registry_status"],
            "self_bond_status": row["self_bond_status"],
            "self_bond_capacity_amount": _num(row["self_bond_capacity_amount"]),
            "self_bond_exposure_amount": _num(calc.self_bond_exposure_amount(row["id"])),
            "violation_points_total": calc.operator_violation_points_total(row["id"]),
            "outstanding_penalty_balance": _num(
                calc.operator_outstanding_penalty_balance(row["id"])
            ),
            "forfeiture_count": row["forfeiture_count"],
            "refund_due_amount": _num(row["refund_due_amount"]),
        },
    )


def mine_site_out(row):
    return _common(
        row,
        {
            "name": row["name"],
            "county": row["county"],
            "total_acres": _num(row["total_acres"]),
            "site_class": row["site_class"],
            "hazard_class": row["hazard_class"],
            "public_safety_score": row["public_safety_score"],
            "water_quality_score": row["water_quality_score"],
            "acres_affected": _num(row["acres_affected"]),
            "legacy_priority_score": _num(row["legacy_priority_score"]),
            "funding_status": row["funding_status"],
            "awarded_funding_amount": _num(row["awarded_funding_amount"]),
            "unfunded_reclamation_need": _num(row["unfunded_reclamation_need"]),
        },
    )


def inspector_profile_out(row):
    return _common(
        row,
        {
            "full_name": row["full_name"],
            "certification_level": row["certification_level"],
            "region": row["region"],
            "scheduled_inspection_count": calc.scheduled_inspection_count(row["id"]),
        },
    )


def permit_out(row):
    return _common(
        row,
        {
            "mine_site_id": row["mine_site_id"],
            "operator_id": row["operator_id"],
            "mining_plan_acres": _num(row["mining_plan_acres"]),
            "post_mining_land_use": row["post_mining_land_use"],
            "proposed_start_date": fmt_ts(row["proposed_start_date"]),
            "status": row["status"],
            "compliance_posture": row["compliance_posture"],
            "bond_basis": row["bond_basis"],
            "bond_required_amount": _num(row["bond_required_amount"]),
            "bond_held_amount": _num(row["bond_held_amount"]),
            "bond_released_to_date": _num(row["bond_released_to_date"]),
            "bond_deficiency_amount": _num(row["bond_deficiency_amount"]),
            "disturbed_acres": _num(row["disturbed_acres"]),
            "reclaimed_acres_credited": _num(row["reclaimed_acres_credited"]),
            "phase1_released_acres": _num(row["phase1_released_acres"]),
            "phase2_released_acres": _num(row["phase2_released_acres"]),
            "phase3_released_acres": _num(row["phase3_released_acres"]),
            "last_notice_end_date": fmt_ts(row["last_notice_end_date"]),
            "issued_at": fmt_ts(row["issued_at"]),
            "denial_reason": row["denial_reason"],
        },
    )


def estimate_out(row):
    return _common(
        row,
        {
            "permit_id": row["permit_id"],
            "estimator_firm": row["estimator_firm"],
            "estimator_license_no": row["estimator_license_no"],
            "estimate_effective_date": fmt_ts(row["estimate_effective_date"]),
            "direct_cost_per_acre": _num(row["direct_cost_per_acre"]),
            "status": row["status"],
            "accepted_at": fmt_ts(row["accepted_at"]),
        },
    )


def instrument_out(row):
    return _common(
        row,
        {
            "permit_id": row["permit_id"],
            "instrument_type": row["instrument_type"],
            "face_amount": _num(row["face_amount"]),
            "surety_company_name": row["surety_company_name"],
            "surety_naic_rating": row["surety_naic_rating"],
            "collateral_type": row["collateral_type"],
            "collateral_market_value": _num(row["collateral_market_value"]),
            "replaces_instrument_id": row["replaces_instrument_id"],
            "credited_amount": _num(row["credited_amount"]),
            "status": row["status"],
            "accepted_by_user_id": row["accepted_by_user_id"],
            "accepted_at": fmt_ts(row["accepted_at"]),
        },
    )


def release_out(row):
    return _common(
        row,
        {
            "permit_id": row["permit_id"],
            "phase": row["phase"],
            "acres_requested": _num(row["acres_requested"]),
            "requested_amount": _num(row["requested_amount"]),
            "approved_amount": _num(row["approved_amount"]),
            "status": row["status"],
            "notice_start_date": fmt_ts(row["notice_start_date"]),
            "notice_end_date": fmt_ts(row["notice_end_date"]),
            "comment_count": row["comment_count"],
            "objection_count": row["objection_count"],
            "objections_resolved": row["objections_resolved"],
            "inspection_id": row["inspection_id"],
            "decided_by_user_id": row["decided_by_user_id"],
            "approved_at": fmt_ts(row["approved_at"]),
            "denial_reason": row["denial_reason"],
            "rescission_reason": row["rescission_reason"],
        },
    )


def inspection_out(row):
    return _common(
        row,
        {
            "permit_id": row["permit_id"],
            "inspector_id": row["inspector_id"],
            "inspection_type": row["inspection_type"],
            "scheduled_start": fmt_ts(row["scheduled_start"]),
            "duration_hours": _num(row["duration_hours"]),
            "scheduled_end": fmt_ts(row["scheduled_end"]),
            "status": row["status"],
            "result": row["result"],
            "findings_note": row["findings_note"],
            "completed_at": fmt_ts(row["completed_at"]),
        },
    )


def notice_out(row):
    return _common(
        row,
        {
            "inspection_id": row["inspection_id"],
            "permit_id": row["permit_id"],
            "violation_class": row["violation_class"],
            "severity_points": row["severity_points"],
            "negligence_points": row["negligence_points"],
            "duration_points": row["duration_points"],
            "history_points": row["history_points"],
            "total_points": row["total_points"],
            "abatement_days": row["abatement_days"],
            "abatement_deadline": fmt_ts(row["abatement_deadline"]),
            "notice_status": row["notice_status"],
            "penalty_status": row["penalty_status"],
            "good_faith_level": row["good_faith_level"],
            "penalty_amount": _num(row["penalty_amount"]),
            "penalty_paid_amount": _num(row["penalty_paid_amount"]),
            "issued_at": fmt_ts(row["issued_at"]),
            "cessation_ordered_at": fmt_ts(row["cessation_ordered_at"]),
            "abated_at": fmt_ts(row["abated_at"]),
            "vacated_at": fmt_ts(row["vacated_at"]),
            "cessation_reason": row["cessation_reason"],
            "abatement_note": row["abatement_note"],
            "vacate_reason": row["vacate_reason"],
        },
    )


def revision_out(row):
    return _common(
        row,
        {
            "permit_id": row["permit_id"],
            "revision_type": row["revision_type"],
            "acreage_delta": _num(row["acreage_delta"]),
            "new_post_mining_land_use": row["new_post_mining_land_use"],
            "sequence_note": row["sequence_note"],
            "status": row["status"],
            "round_count": row["round_count"],
            "info_request_note": row["info_request_note"],
            "response_note": row["response_note"],
            "denial_reason": row["denial_reason"],
            "decided_at": fmt_ts(row["decided_at"]),
        },
    )


def proceeding_out(row):
    return _common(
        row,
        {
            "permit_id": row["permit_id"],
            "initiation_reason": row["initiation_reason"],
            "status": row["status"],
            "contest_note": row["contest_note"],
            "contest_deadline": fmt_ts(row["contest_deadline"]),
            "forfeited_bond_amount": _num(row["forfeited_bond_amount"]),
            "state_reclamation_cost_estimate": _num(row["state_reclamation_cost_estimate"]),
            "actual_cost_incurred": _num(row["actual_cost_incurred"]),
            "completion_pct": _num(row["completion_pct"]),
            "deficiency_amount": _num(row["deficiency_amount"]),
            "surplus_amount": _num(row["surplus_amount"]),
            "finalized_at": fmt_ts(row["finalized_at"]),
            "completed_at": fmt_ts(row["completed_at"]),
        },
    )


def many(fn, rows):
    return [fn(row) for row in rows]
