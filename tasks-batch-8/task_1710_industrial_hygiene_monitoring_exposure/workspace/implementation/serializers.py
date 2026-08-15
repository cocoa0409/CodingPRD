"""Entity -> public-dict serializers.

Every resource carries id / created_at / updated_at / version (PRD section
2.4). Stored Decimals are emitted as JSON numbers; internal bookkeeping keys
(prefixed with "_") never leak.
"""

from helpers import public_num


def site_out(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "industry_code": e["industry_code"],
        "retention_years": e["retention_years"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def employee_out(e):
    return {
        "id": e["id"],
        "site_id": e["site_id"],
        "full_name": e["full_name"],
        "external_ref": e["external_ref"],
        "job_title": e["job_title"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def exposure_limit_out(e):
    return {
        "id": e["id"],
        "analyte_code": e["analyte_code"],
        "basis": e["basis"],
        "limit_type": e["limit_type"],
        "limit_mg_m3": public_num(e["limit_mg_m3"]),
        "action_fraction": public_num(e["action_fraction"]),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def seg_out(e):
    return {
        "id": e["id"],
        "site_id": e["site_id"],
        "name": e["name"],
        "analyte_code": e["analyte_code"],
        "exposure_limit_id": e["exposure_limit_id"],
        "task_description": e["task_description"],
        "headcount": e["headcount"],
        "current_class": e["current_class"],
        "next_sample_due_date": e["next_sample_due_date"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def membership_out(e):
    return {
        "id": e["id"],
        "seg_id": e["seg_id"],
        "employee_id": e["employee_id"],
        "is_primary": e["is_primary"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def plan_out(e):
    return {
        "id": e["id"],
        "seg_id": e["seg_id"],
        "purpose": e["purpose"],
        "planned_start_date": e["planned_start_date"],
        "planned_end_date": e["planned_end_date"],
        "unsampled_time_rule": e["unsampled_time_rule"],
        "volume_basis": e["volume_basis"],
        "required_sample_count": e["required_sample_count"],
        "active_sample_count": e["active_sample_count"],
        "analyzed_valid_count": e["analyzed_valid_count"],
        "created_by_user_id": e["created_by_user_id"],
        "approved_by_user_id": e["approved_by_user_id"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def pump_out(e):
    return {
        "id": e["id"],
        "site_id": e["site_id"],
        "serial_number": e["serial_number"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def calibration_out(e):
    return {
        "id": e["id"],
        "pump_id": e["pump_id"],
        "pre_flow_lpm": public_num(e["pre_flow_lpm"]),
        "post_flow_lpm": public_num(e["post_flow_lpm"]),
        "drift_pct": public_num(e["drift_pct"]),
        "result": e["result"],
        "performed_by_user_id": e["performed_by_user_id"],
        "linked_sample_id": e["linked_sample_id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def sample_out(e):
    return {
        "id": e["id"],
        "sampling_plan_id": e["sampling_plan_id"],
        "sample_type": e["sample_type"],
        "employee_id": e["employee_id"],
        "pump_id": e["pump_id"],
        "pre_calibration_id": e["pre_calibration_id"],
        "collection_date": e["collection_date"],
        "start_minute": e["start_minute"],
        "duration_minutes": e["duration_minutes"],
        "collected_by_user_id": e["collected_by_user_id"],
        "status": e["status"],
        "invalidate_reason": e["invalidate_reason"],
        "air_volume_liters": public_num(e["air_volume_liters"]),
        "concentration_mg_m3": public_num(e["concentration_mg_m3"]),
        "sample_twa_mg_m3": public_num(e["sample_twa_mg_m3"]),
        "is_detect": e["is_detect"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def batch_out(e):
    return {
        "id": e["id"],
        "site_id": e["site_id"],
        "analyte_code": e["analyte_code"],
        "lod_ug": public_num(e["lod_ug"]),
        "loq_ug": public_num(e["loq_ug"]),
        "window_start_date": e["window_start_date"],
        "window_end_date": e["window_end_date"],
        "max_capacity": e["max_capacity"],
        "intake_count": e["intake_count"],
        "contaminated": e["contaminated"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def result_out(e):
    return {
        "id": e["id"],
        "field_sample_id": e["field_sample_id"],
        "lab_batch_id": e["lab_batch_id"],
        "mass_ug": public_num(e["mass_ug"]),
        "entered_by_user_id": e["entered_by_user_id"],
        "reported_at": e["reported_at"],
        "is_detect": e["is_detect"],
        "is_quantifiable": e["is_quantifiable"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def assessment_out(e):
    return {
        "id": e["id"],
        "seg_id": e["seg_id"],
        "sampling_plan_id": e["sampling_plan_id"],
        "supersedes_assessment_id": e["supersedes_assessment_id"],
        "n_valid": e["n_valid"],
        "substitution_rule": e["substitution_rule"],
        "geo_mean": public_num(e["geo_mean"]),
        "gsd": public_num(e["gsd"]),
        "ucl95": public_num(e["ucl95"]),
        "lcl95": public_num(e["lcl95"]),
        "exposure_class": e["exposure_class"],
        "adjusted_class": e["adjusted_class"],
        "review_status": e["review_status"],
        "is_current": e["is_current"],
        "prepared_by_user_id": e["prepared_by_user_id"],
        "signed_by_user_id": e["signed_by_user_id"],
        "signed_at": e["signed_at"],
        "retention_until": e["retention_until"],
        "legal_hold": e["legal_hold"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def control_out(e):
    return {
        "id": e["id"],
        "exposure_assessment_id": e["exposure_assessment_id"],
        "control_type": e["control_type"],
        "description": e["description"],
        "priority": e["priority"],
        "assigned_protection_factor": public_num(e["assigned_protection_factor"]),
        "auto_created": e["auto_created"],
        "verification_plan_id": e["verification_plan_id"],
        "implemented_at": e["implemented_at"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def notification_out(e):
    return {
        "id": e["id"],
        "employee_id": e["employee_id"],
        "exposure_assessment_id": e["exposure_assessment_id"],
        "due_date": e["due_date"],
        "status": e["status"],
        "sent_at": e["sent_at"],
        "sent_by_user_id": e["sent_by_user_id"],
        "acknowledged_at": e["acknowledged_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def clearance_out(e):
    return {
        "id": e["id"],
        "employee_id": e["employee_id"],
        "status": e["status"],
        "decided_at": e["decided_at"],
        "expiry_date": e["expiry_date"],
        "decided_by_user_id": e["decided_by_user_id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def fit_test_out(e):
    return {
        "id": e["id"],
        "employee_id": e["employee_id"],
        "medical_clearance_id": e["medical_clearance_id"],
        "respirator_model": e["respirator_model"],
        "test_date": e["test_date"],
        "expiry_date": e["expiry_date"],
        "status": e["status"],
        "recorded_by_user_id": e["recorded_by_user_id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }
