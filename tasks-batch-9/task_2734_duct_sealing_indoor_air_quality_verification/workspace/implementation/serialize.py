"""Entity serialisers.  Field names follow SCAFFOLD section 1.1 exactly."""

from decimal import Decimal

import lookup
from store import iso


def num(value):
    """Render a stored numeric as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value() and abs(value) < Decimal("1e15"):
            as_float = float(value)
            return as_float
        return float(value)
    return value


def ts(value):
    """Render a stored instant.  Datetimes are canonicalised, strings pass through."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return iso(value)


def utility_program(row):
    committed, paid, remaining = lookup.program_ledger(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "rebate_basis": row["rebate_basis"],
        "rate_cents_per_cfm_reduced": row["rate_cents_per_cfm_reduced"],
        "pct_of_invoice_bps": row["pct_of_invoice_bps"],
        "cap_cents": row["cap_cents"],
        "annual_budget_cents": row["annual_budget_cents"],
        "min_reduction_pct": num(row["min_reduction_pct"]),
        "requires_inspector_verification": row["requires_inspector_verification"],
        "combustion_safety_required": row["combustion_safety_required"],
        "committed_rebate_cents": committed,
        "paid_rebate_cents": paid,
        "remaining_budget_cents": remaining,
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def technician(row):
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "license_number": row["license_number"],
        "certification_status": row["certification_status"],
        "certification_expires_at": ts(row["certification_expires_at"]),
        "open_seal_job_count": lookup.open_seal_job_count(row["id"]),
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def project(row):
    total, eligible = lookup.duct_system_counts(row["id"])
    on_hold = row["status"] == "SAFETY_HOLD"
    return {
        "id": row["id"],
        "utility_program_id": row["utility_program_id"],
        "address_line": row["address_line"],
        "conditioned_floor_area_sqft": row["conditioned_floor_area_sqft"],
        "gas_appliance_count": row["gas_appliance_count"],
        "invoice_amount_cents": row["invoice_amount_cents"],
        "status": row["status"],
        "safety_hold": on_hold,
        "safety_hold_reason": row["safety_hold_reason"] if on_hold else None,
        "duct_system_count": total,
        "eligible_duct_system_count": eligible,
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def duct_system(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "system_label": row["system_label"],
        "total_register_count": row["total_register_count"],
        "design_cfm": num(row["design_cfm"]),
        "duct_material": row["duct_material"],
        "condition_grade": row["condition_grade"],
        "asbestos_screening_result": row["asbestos_screening_result"],
        "lab_reference": row["lab_reference"],
        "eligibility_status": row["eligibility_status"],
        "exclusion_reason": row["exclusion_reason"] if row["eligibility_status"] == "EXCLUDED" else None,
        "seal_status": row["seal_status"],
        "baseline_leakage_cfm25": num(row["baseline_leakage_cfm25"]),
        "working_leakage_cfm25": num(row["working_leakage_cfm25"]),
        "sealed_leakage_reduction_cfm": num(row["sealed_leakage_reduction_cfm"]),
        "active_seal_job_id": lookup.active_seal_job_id(row["id"]),
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def leakage_test(row):
    return {
        "id": row["id"],
        "duct_system_id": row["duct_system_id"],
        "phase": row["phase"],
        "method": row["method"],
        "window_start_at": ts(row["window_start_at"]),
        "window_end_at": ts(row["window_end_at"]),
        "status": row["status"],
        "test_pressure_pa": num(row["test_pressure_pa"]),
        "fan_ring_config": row["fan_ring_config"],
        "masked_register_count": row["masked_register_count"],
        "measured_leakage_cfm": num(row["measured_leakage_cfm"]),
        "ambient_temp_f": num(row["ambient_temp_f"]),
        "normalized_leakage_cfm25": num(row["normalized_leakage_cfm25"]),
        "leakage_per_100_sqft": num(row["leakage_per_100_sqft"]),
        "performed_by_user_id": row["performed_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "review_note": row["review_note"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def seal_job(row):
    return {
        "id": row["id"],
        "duct_system_id": row["duct_system_id"],
        "pre_test_id": row["pre_test_id"],
        "technician_id": row["technician_id"],
        "retest_of_job_id": row["retest_of_job_id"],
        "scheduled_start_at": ts(row["scheduled_start_at"]),
        "scheduled_end_at": ts(row["scheduled_end_at"]),
        "target_leakage_cfm": num(row["target_leakage_cfm"]),
        "status": row["status"],
        "masked_register_labels": list(row["masked_register_labels"]),
        "masked_register_count": len(row["masked_register_labels"]),
        "sample_count": row["sample_count"],
        "current_leakage_cfm": num(row["current_leakage_cfm"]),
        "target_reached": row["target_reached"],
        "stall_flag": row["stall_flag"],
        "pause_count": row["pause_count"],
        "sealant_lbs_used": num(row["sealant_lbs_used"]),
        "abort_reason": row["abort_reason"],
        "warranty_suspended": row["warranty_suspended"],
        "warranty_status": lookup.warranty_status(row),
        "warranty_registered_at": ts(row["warranty_registered_at"]),
        "retest_due_at": ts(row["retest_due_at"]),
        "homeowner_name": row["homeowner_name"],
        "homeowner_email": row["homeowner_email"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def leakage_sample(row):
    return {
        "id": row["id"],
        "seal_job_id": row["seal_job_id"],
        "sample_seq": row["sample_seq"],
        "elapsed_seconds": row["elapsed_seconds"],
        "instantaneous_leakage_cfm": num(row["instantaneous_leakage_cfm"]),
        "injection_pressure_pa": num(row["injection_pressure_pa"]),
        "seal_rate_cfm_per_min": num(row["seal_rate_cfm_per_min"]),
        "cutoff_triggered": row["cutoff_triggered"],
        "created_at": ts(row["created_at"]),
    }


def combustion_test(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "appliance_label": row["appliance_label"],
        "appliance_type": row["appliance_type"],
        "phase": row["phase"],
        "spillage_seconds": row["spillage_seconds"],
        "co_ppm_air_free": num(row["co_ppm_air_free"]),
        "draft_pressure_pa": num(row["draft_pressure_pa"]),
        "worst_case_depressurization_pa": num(row["worst_case_depressurization_pa"]),
        "verdict": row["verdict"],
        "performed_by_user_id": row["performed_by_user_id"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def verification_report(row):
    return {
        "id": row["id"],
        "seal_job_id": row["seal_job_id"],
        "post_test_id": row["post_test_id"],
        "status": row["status"],
        "pre_leakage_cfm25": num(row["pre_leakage_cfm25"]),
        "post_leakage_cfm25": num(row["post_leakage_cfm25"]),
        "reduction_pct_system_basis": num(row["reduction_pct_system_basis"]),
        "reduction_pct_whole_house_basis": num(row["reduction_pct_whole_house_basis"]),
        "cfm_reduced_whole_house": num(row["cfm_reduced_whole_house"]),
        "guarantee_threshold_pct": num(row["guarantee_threshold_pct"]),
        "guarantee_met": row["guarantee_met"],
        "issued_by_user_id": row["issued_by_user_id"],
        "issued_at": ts(row["issued_at"]),
        "signature_note": row["signature_note"],
        "correction_round": row["correction_round"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def rebate_claim(row):
    return {
        "id": row["id"],
        "verification_report_id": row["verification_report_id"],
        "utility_program_id": row["utility_program_id"],
        "documentation_bundle_ref": row["documentation_bundle_ref"],
        "status": row["status"],
        "per_cfm_candidate_cents": row["per_cfm_candidate_cents"],
        "percent_of_invoice_candidate_cents": row["percent_of_invoice_candidate_cents"],
        "basis_applied": row["basis_applied"],
        "tier_bonus_pct": num(row["tier_bonus_pct"]),
        "capped_subtotal_cents": row["capped_subtotal_cents"],
        "admin_fee_cents": row["admin_fee_cents"],
        "payable_cents": row["payable_cents"],
        "committed": row["status"] in ("SUBMITTED", "APPROVED"),
        "inspector_user_id": row["inspector_user_id"],
        "spot_check_leakage_cfm": num(row["spot_check_leakage_cfm"]),
        "spot_check_pressure_pa": num(row["spot_check_pressure_pa"]),
        "spot_check_cfm25": num(row["spot_check_cfm25"]),
        "inspector_variance_pct": num(row["inspector_variance_pct"]),
        "inspector_outcome": row["inspector_outcome"],
        "resubmission_count": row["resubmission_count"],
        "payment_reference": row["payment_reference"],
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def comfort_complaint(row):
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "room_label": row["room_label"],
        "complaint_type": row["complaint_type"],
        "reported_by": row["reported_by"],
        "status": row["status"],
        "diagnosis_code": row["diagnosis_code"],
        "tolerance_pct": num(row["tolerance_pct"]),
        "balanced_room_count": lookup.balanced_room_count(row["id"]),
        "rebalance_count": row["rebalance_count"],
        "damper_adjustment_note": row["damper_adjustment_note"],
        "resolved_at": ts(row["resolved_at"]),
        "created_at": ts(row["created_at"]),
        "updated_at": ts(row["updated_at"]),
        "version": row["version"],
    }


def airflow_reading(row):
    return {
        "id": row["id"],
        "comfort_complaint_id": row["comfort_complaint_id"],
        "room_label": row["room_label"],
        "reading_seq": row["reading_seq"],
        "measured_cfm": num(row["measured_cfm"]),
        "design_cfm": num(row["design_cfm"]),
        "damper_position_pct": num(row["damper_position_pct"]),
        "deviation_pct": num(row["deviation_pct"]),
        "within_tolerance": row["within_tolerance"],
        "measured_by_user_id": row["measured_by_user_id"],
        "created_at": ts(row["created_at"]),
    }
