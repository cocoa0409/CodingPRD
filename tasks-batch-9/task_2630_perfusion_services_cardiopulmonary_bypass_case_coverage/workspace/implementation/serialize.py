"""Entity serialisers -- field names taken verbatim from SCAFFOLD section 1.1."""

import calc
from envelope import iso as iso_stamp
from envelope import iso_instant as iso


def _d(value):
    return value.isoformat() if value is not None else None


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso_stamp(row["created_at"]),
        "updated_at": iso_stamp(row["updated_at"]),
        "version": row["version"],
    }


def contract(row):
    out = {
        "hospital_name": row["hospital_name"],
        "staffing_model": row["staffing_model"],
        "monthly_coverage_fee_cents": row["monthly_coverage_fee_cents"],
        "per_case_fee_cents": row["per_case_fee_cents"],
        "ecmo_hourly_fee_cents": row["ecmo_hourly_fee_cents"],
        "prolonged_surcharge_pct": calc.num(row["prolonged_surcharge_pct"]),
        "prolonged_pump_threshold_minutes": row["prolonged_pump_threshold_minutes"],
        "disposable_markup_pct": calc.num(row["disposable_markup_pct"]),
        "disposable_discount_pct": calc.num(row["disposable_discount_pct"]),
        "monthly_case_cap": row["monthly_case_cap"],
        "accrued_case_fee_cents": row["accrued_case_fee_cents"],
        "accrued_case_count": row["accrued_case_count"],
        "coverage_posture": row["coverage_posture"],
        "last_settlement_period": row["last_settlement_period"],
    }
    out.update(_common(row))
    return out


def surgeon(row):
    out = {
        "full_name": row["full_name"],
        "npi_code": row["npi_code"],
        "specialty": row["specialty"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def preference_card(row):
    out = {
        "surgeon_id": row["surgeon_id"],
        "procedure_type": row["procedure_type"],
        "revision": row["revision"],
        "status": row["status"],
        "standard_pump_minutes": row["standard_pump_minutes"],
        "prime_volume_ml": row["prime_volume_ml"],
        "pack_line_items": [dict(li) for li in row["pack_line_items"]],
        "required_safety_check_codes": list(row["required_safety_check_codes"]),
        "blood_management_protocol": row["blood_management_protocol"],
        "min_hematocrit_pct": calc.num(row["min_hematocrit_pct"]),
    }
    out.update(_common(row))
    return out


def perfusionist(row):
    out = {
        "full_name": row["full_name"],
        "employee_code": row["employee_code"],
        "employment_status": row["employment_status"],
        "is_chief": row["is_chief"],
        "ecmo_privileged": row["ecmo_privileged"],
        "career_case_count": row["career_case_count"],
        "ce_credits_verified": calc.num(row["ce_credits_verified"]),
        "ce_credits_pending": calc.num(row["ce_credits_pending"]),
        "readiness_score": calc.num(row["readiness_score"]),
        "readiness_variant_last": row["readiness_variant_last"],
        "consecutive_case_count_24h": calc.consecutive_case_count_24h(row["id"]),
        "ecmo_hours_rolling_7d": calc.ecmo_hours_rolling_7d(row["id"]),
    }
    out.update(_common(row))
    return out


def certification(row):
    out = {
        "perfusionist_id": row["perfusionist_id"],
        "cert_code": row["cert_code"],
        "status": row["status"],
        "issued_on": iso(row["issued_on"]),
        "expires_on": iso(row["expires_on"]),
        "cycle_credit_requirement": row["cycle_credit_requirement"],
        "remediation_credits_required": calc.num(row["remediation_credits_required"]),
        "probation_credits_banked": calc.num(row["probation_credits_banked"]),
        "probation_count": row["probation_count"],
    }
    out.update(_common(row))
    return out


def ce_activity(row):
    out = {
        "perfusionist_id": row["perfusionist_id"],
        "category": row["category"],
        "credit_hours": calc.num(row["credit_hours"]),
        "activity_date": iso(row["activity_date"]),
        "accreditation_body": row["accreditation_body"],
        "status": row["status"],
        "counted_toward_remediation": row["counted_toward_remediation"],
    }
    out.update(_common(row))
    return out


def device(row):
    out = {
        "contract_id": row["contract_id"],
        "asset_tag": row["asset_tag"],
        "device_class": row["device_class"],
        "status": row["status"],
        "backup_device_id": row["backup_device_id"],
        "service_interval_hours": row["service_interval_hours"],
        "runtime_hours_since_service": calc.num(row["runtime_hours_since_service"]),
        "alarm_count_since_service": row["alarm_count_since_service"],
        "last_service_completed_at": iso(row["last_service_completed_at"]),
        "open_reservation_count": calc.device_open_reservation_count(row["id"]),
    }
    out.update(_common(row))
    return out


def event_log(row):
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "event_code": row["event_code"],
        "runtime_hours_delta": calc.num(row["runtime_hours_delta"]),
        "recorded_by_user_id": row["recorded_by_user_id"],
        "detail": row["detail"],
        "created_at": iso_stamp(row["created_at"]),
    }


def slot(row):
    out = {
        "contract_id": row["contract_id"],
        "perfusionist_id": row["perfusionist_id"],
        "slot_type": row["slot_type"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "status": row["status"],
        "consumed": row["consumed"],
    }
    out.update(_common(row))
    return out


def bypass_case(row):
    out = {
        "contract_id": row["contract_id"],
        "surgeon_id": row["surgeon_id"],
        "assigned_perfusionist_id": row["assigned_perfusionist_id"],
        "primary_device_id": row["primary_device_id"],
        "backup_device_id": row["backup_device_id"],
        "procedure_type": row["procedure_type"],
        "acuity": row["acuity"],
        "scheduled_start": iso(row["scheduled_start"]),
        "scheduled_end": iso(row["scheduled_end"]),
        "bypass_status": row["bypass_status"],
        "billing_status": row["billing_status"],
        "bypass_started_at": iso(row["bypass_started_at"]),
        "bypass_ended_at": iso(row["bypass_ended_at"]),
        "pump_time_minutes": row["pump_time_minutes"],
        "cross_clamp_minutes": row["cross_clamp_minutes"],
        "lowest_hematocrit_pct": calc.num(row["lowest_hematocrit_pct"]),
        "adverse_event_count": row["adverse_event_count"],
        "provisional_fee_cents": row["provisional_fee_cents"],
        "final_fee_cents": row["final_fee_cents"],
        "accrued_fee_cents": row["accrued_fee_cents"],
        "readiness_flag": row["readiness_flag"],
        "setup_verified_at": iso(row["setup_verified_at"]),
    }
    out.update(_common(row))
    return out


def pack(row):
    out = {
        "case_id": row["case_id"],
        "applied_preference_card_id": row["applied_preference_card_id"],
        "line_items": [dict(li) for li in row["line_items"]],
        "substitutions": [dict(s) for s in row["substitutions"]],
        "requires_surgeon_approval": row["requires_surgeon_approval"],
        "approval_status": row["approval_status"],
        "pack_cost_cents": row["pack_cost_cents"],
        "prime_volume_ml": row["prime_volume_ml"],
    }
    out.update(_common(row))
    return out


def checklist(row):
    out = {
        "case_id": row["case_id"],
        "verified_by_perfusionist_id": row["verified_by_perfusionist_id"],
        "check_results": [dict(cr) for cr in row["check_results"]],
        "blood_management_protocol": row["blood_management_protocol"],
        "hematocrit_pct": calc.num(row["hematocrit_pct"]),
        "blood_mgmt_signoff": row["blood_mgmt_signoff"],
        "status": row["status"],
        "verified_at": iso(row["verified_at"]),
        "missing_check_codes": list(row["missing_check_codes"]),
    }
    out.update(_common(row))
    return out


def ecmo_run(row):
    out = {
        "case_id": row["case_id"],
        "primary_perfusionist_id": row["primary_perfusionist_id"],
        "relief_slot_id": row["relief_slot_id"],
        "mode": row["mode"],
        "cannulated_at": iso(row["cannulated_at"]),
        "last_handoff_at": iso(row["last_handoff_at"]),
        "decannulated_at": iso(row["decannulated_at"]),
        "status": row["status"],
        "uninterrupted_minutes": calc.num(calc.run_uninterrupted_minutes(row)),
        "billable_hours": row["billable_hours"],
        "staffing_breach": calc.run_staffing_breach(row),
        "ecmo_fee_cents": row["ecmo_fee_cents"],
    }
    out.update(_common(row))
    return out


def incident(row):
    out = {
        "case_id": row["case_id"],
        "involved_perfusionist_id": row["involved_perfusionist_id"],
        "filed_by_perfusionist_id": row["filed_by_perfusionist_id"],
        "closed_by_perfusionist_id": row["closed_by_perfusionist_id"],
        "severity": row["severity"],
        "category": row["category"],
        "narrative": row["narrative"],
        "status": row["status"],
        "return_count": row["return_count"],
        "reviewed_readiness_score": calc.num(row["reviewed_readiness_score"]),
        "finding": row["finding"],
        "corrective_action_required": row["corrective_action_required"],
    }
    out.update(_common(row))
    return out
