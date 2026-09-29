"""Row -> JSON projection. Derived values are refreshed at read time so that a
read never reports a stale ledger, while `version` moves only where a workflow
says it should."""
from decimal import Decimal

import db
import derive


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, out, versioned=True):
    out["created_at"] = row["created_at"]
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def claimant(row):
    derive.recompute_claimant(row)
    return _common(row, {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "contact_email": row["contact_email"],
        "entity_type": row["entity_type"],
        "standing_status": row["standing_status"],
        "outstanding_fee_balance_usd": num(row["outstanding_fee_balance_usd"]),
        "open_application_count": row["open_application_count"],
    })


def water_right(row):
    # PRD §2.9/§2.10 make the four volume buckets and the status derived, so a
    # read re-derives them. PRD §3.2 does not list a read among the events that
    # move the abandonment projection, so the stored score is left alone.
    derive.recompute_right(row, refresh_score=False)
    return _common(row, {
        "id": row["id"],
        "claimant_id": row["claimant_id"],
        "right_number": row["right_number"],
        "priority_date": row["priority_date"],
        "source_stream_code": row["source_stream_code"],
        "purpose_of_use": row["purpose_of_use"],
        "place_of_use_acres": num(row["place_of_use_acres"]),
        "authorized_diversion_af": num(row["authorized_diversion_af"]),
        "authorized_rate_cfs": num(row["authorized_rate_cfs"]),
        "status": row["status"],
        "certified_hcu_af": num(row["certified_hcu_af"]),
        "encumbered_af": num(row["encumbered_af"]),
        "transferred_away_af": num(row["transferred_away_af"]),
        "transferable_af": num(row["transferable_af"]),
        "forfeiture_risk_score": num(row["forfeiture_risk_score"]),
        "forfeiture_risk_band": row["forfeiture_risk_band"],
        "consecutive_nonuse_years": row["consecutive_nonuse_years"],
        "bank_enrolled": row["bank_enrolled"],
        "pending_review_count": row["pending_review_count"],
    })


def point_of_diversion(row):
    return _common(row, {
        "id": row["id"],
        "water_right_id": row["water_right_id"],
        "legal_description": row["legal_description"],
        "stream_reach_code": row["stream_reach_code"],
        "max_rate_cfs": num(row["max_rate_cfs"]),
        "stream_miles_from_headwater": num(row["stream_miles_from_headwater"]),
        "status": row["status"],
    })


def beneficial_use_record(row):
    return _common(row, {
        "id": row["id"],
        "water_right_id": row["water_right_id"],
        "use_year": row["use_year"],
        "reported_diversion_af": num(row["reported_diversion_af"]),
        "irrigated_acres": num(row["irrigated_acres"]),
        "verification_source": row["verification_source"],
        "reported_by_user_id": row["reported_by_user_id"],
    }, versioned=False)


def hcu_study(row):
    return _common(row, {
        "id": row["id"],
        "water_right_id": row["water_right_id"],
        "method": row["method"],
        "study_period_start_year": row["study_period_start_year"],
        "study_period_end_year": row["study_period_end_year"],
        "qualifying_year_count": row["qualifying_year_count"],
        "average_annual_cu_af": num(row["average_annual_cu_af"]),
        "short_history_haircut_applied": row["short_history_haircut_applied"],
        "transferable_cu_af": num(row["transferable_cu_af"]),
        "status": row["status"],
        "certified_by_user_id": row["certified_by_user_id"],
        "certified_at": row["certified_at"],
    })


def transfer_application(row):
    derive.recompute_app(row)
    return _common(row, {
        "id": row["id"],
        "water_right_id": row["water_right_id"],
        "hcu_study_id": row["hcu_study_id"],
        "proposed_point_of_diversion_id": row["proposed_point_of_diversion_id"],
        "application_type": row["application_type"],
        "requested_af": num(row["requested_af"]),
        "proposed_purpose_of_use": row["proposed_purpose_of_use"],
        "proposed_place_of_use_acres": num(row["proposed_place_of_use_acres"]),
        "status": row["status"],
        "revision_round": row["revision_round"],
        "protest_deadline": row["protest_deadline"],
        "unresolved_protest_count": row["unresolved_protest_count"],
        "escrowed_af": num(row["escrowed_af"]),
        "mitigation_fee_total_usd": num(row["mitigation_fee_total_usd"]),
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_note": row["decision_note"],
    })


def injury_analysis(row):
    return _common(row, {
        "id": row["id"],
        "transfer_application_id": row["transfer_application_id"],
        "method": row["method"],
        "pod_move_miles": num(row["pod_move_miles"]),
        "return_flow_credit_af": num(row["return_flow_credit_af"]),
        "offset_af": num(row["offset_af"]),
        "gross_depletion_af": num(row["gross_depletion_af"]),
        "net_injury_af": num(row["net_injury_af"]),
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
    })


def protest(row):
    return _common(row, {
        "id": row["id"],
        "transfer_application_id": row["transfer_application_id"],
        "protestant_claimant_id": row["protestant_claimant_id"],
        "claimed_injury_af": num(row["claimed_injury_af"]),
        "basis": row["basis"],
        "track": row["track"],
        "status": row["status"],
        "stipulated_offset_af": num(row["stipulated_offset_af"]),
        "resolution_note": row["resolution_note"],
        "resolved_by_user_id": row["resolved_by_user_id"],
    })


def approval_condition(row):
    return _common(row, {
        "id": row["id"],
        "transfer_application_id": row["transfer_application_id"],
        "condition_type": row["condition_type"],
        "required_af": num(row["required_af"]),
        "compliance_due_date": row["compliance_due_date"],
        "source": row["source"],
        "status": row["status"],
        "payment_status": row["payment_status"],
        "base_fee_usd": num(row["base_fee_usd"]),
        "surcharge_pct": num(row["surcharge_pct"]),
        "admin_surcharge_usd": num(row["admin_surcharge_usd"]),
        "total_fee_usd": num(row["total_fee_usd"]),
        "imposed_by_user_id": row["imposed_by_user_id"],
    })


def water_bank_account(row):
    derive.recompute_account(row)
    return _common(row, {
        "id": row["id"],
        "claimant_id": row["claimant_id"],
        "basin_code": row["basin_code"],
        "deposited_credit_af": num(row["deposited_credit_af"]),
        "committed_credit_af": num(row["committed_credit_af"]),
        "leased_out_af": num(row["leased_out_af"]),
        "available_credit_af": num(row["available_credit_af"]),
        "suspended_lease_count": row["suspended_lease_count"],
        "posture": row["posture"],
    })


def lease_assignment(row):
    return _common(row, {
        "id": row["id"],
        "water_bank_account_id": row["water_bank_account_id"],
        "water_right_id": row["water_right_id"],
        "point_of_diversion_id": row["point_of_diversion_id"],
        "lessee_name": row["lessee_name"],
        "lease_start_date": row["lease_start_date"],
        "lease_end_date": row["lease_end_date"],
        "requested_af": num(row["requested_af"]),
        "diversion_rate_cfs": num(row["diversion_rate_cfs"]),
        "rental_rate_usd_per_af": num(row["rental_rate_usd_per_af"]),
        "valuation_method": row["valuation_method"],
        "status": row["status"],
        "used_af": num(row["used_af"]),
        "settlement_credit_af": num(row["settlement_credit_af"]),
        "suspension_count": row["suspension_count"],
    })


def decree_docket(row):
    derive.recompute_docket(row)
    return _common(row, {
        "id": row["id"],
        "basin_code": row["basin_code"],
        "docket_number": row["docket_number"],
        "claim_filing_deadline": row["claim_filing_deadline"],
        "phase": row["phase"],
        "claim_count": row["claim_count"],
        "decreed_claim_count": row["decreed_claim_count"],
        "total_decreed_af": num(row["total_decreed_af"]),
    })


def adjudication_claim(row):
    return _common(row, {
        "id": row["id"],
        "decree_docket_id": row["decree_docket_id"],
        "water_right_id": row["water_right_id"],
        "claimed_priority_date": row["claimed_priority_date"],
        "claimed_af": num(row["claimed_af"]),
        "filing_status": row["filing_status"],
        "verification_status": row["verification_status"],
        "examiner_recommended_af": num(row["examiner_recommended_af"]),
        "decreed_af": num(row["decreed_af"]),
        "objection_count": row["objection_count"],
        "priority_rank": row["priority_rank"],
    })
