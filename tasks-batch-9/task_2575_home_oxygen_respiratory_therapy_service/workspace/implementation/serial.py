"""Representation builders -- one per entity (SCAFFOLD 1.1 field lists).

QualifyingTest is immutable and therefore carries only id and created_at:
it has no updated_at and no version at all.
"""
from calc import remediated_unit_count
from core import iso, iso_date, num2


def branch_out(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "state_code": row["state_code"],
        "competitive_bid_area": row["competitive_bid_area"],
        "liquid_oxygen_certified": row["liquid_oxygen_certified"],
        "refill_capacity_per_day": row["refill_capacity_per_day"],
        "tank_exchange_buffer_minutes": row["tank_exchange_buffer_minutes"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def patient_out(row):
    return {
        "id": row["id"],
        "mrn": row["mrn"],
        "full_name": row["full_name"],
        "branch_id": row["branch_id"],
        "payer_type": row["payer_type"],
        "mobility_profile": row["mobility_profile"],
        "altitude_feet": row["altitude_feet"],
        "status": row["status"],
        "transfer_to_branch_id": row["transfer_to_branch_id"],
        "transfer_effective_date": iso_date(row["transfer_effective_date"]),
        "current_cmn_status": row["current_cmn_status"],
        "oxygen_safety_risk_score": num2(row["oxygen_safety_risk_score"]),
        "risk_variant_applied": row["risk_variant_applied"],
        "compliance_hold": row["compliance_hold"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def qualifying_test_out(row):
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "test_type": row["test_type"],
        "spo2_percent": row["spo2_percent"],
        "pao2_mmhg": row["pao2_mmhg"],
        "desat_minutes": row["desat_minutes"],
        "cor_pulmonale_or_edema": row["cor_pulmonale_or_edema"],
        "tested_at": iso(row["tested_at"]),
        "ordering_physician_npi": row["ordering_physician_npi"],
        "qualifying_group": row["qualifying_group"],
        "validity_days": row["validity_days"],
        "test_validity_expires_at": iso(row["test_validity_expires_at"]),
        "created_at": iso(row["created_at"]),
    }


def cmn_out(row):
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "qualifying_test_id": row["qualifying_test_id"],
        "form_type": row["form_type"],
        "prescribed_lpm": row["prescribed_lpm"],
        "hours_per_day": row["hours_per_day"],
        "portable_prescribed": row["portable_prescribed"],
        "length_of_need_months": row["length_of_need_months"],
        "narrative_element_count": row["narrative_element_count"],
        "status": row["status"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "signed_by_user_id": row["signed_by_user_id"],
        "audited_by_user_id": row["audited_by_user_id"],
        "physician_signature_date": iso_date(row["physician_signature_date"]),
        "initial_date": iso_date(row["initial_date"]),
        "recert_due_date": iso_date(row["recert_due_date"]),
        "revision_round": row["revision_round"],
        "correction_notes": row["correction_notes"],
        "void_reason": row["void_reason"],
        "documentation_score": num2(row["documentation_score"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def posted_month_out(entry):
    return {
        "service_month": entry["service_month"],
        "amount_cents": entry["amount_cents"],
        "days_in_service": entry["days_in_service"],
        "posted_at": iso(entry["posted_at"]),
    }


def contract_out(row):
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "cmn_id": row["cmn_id"],
        "pricing_basis": row["pricing_basis"],
        "cap_month_limit": row["cap_month_limit"],
        "billing_status": row["billing_status"],
        "service_status": row["service_status"],
        "suspension_reason": row["suspension_reason"],
        "first_service_month": row["first_service_month"],
        "monthly_allowable_cents": row["monthly_allowable_cents"],
        "posted_months": [posted_month_out(e) for e in row["posted_months"]],
        "posted_month_count": row["posted_month_count"],
        "lifetime_paid_cents": row["lifetime_paid_cents"],
        "last_posted_service_month": row["last_posted_service_month"],
        "malfunction_count": row["malfunction_count"],
        "cumulative_oxygen_gap_minutes": row["cumulative_oxygen_gap_minutes"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def equipment_unit_out(row):
    return {
        "id": row["id"],
        "branch_id": row["branch_id"],
        "serial_number": row["serial_number"],
        "model_code": row["model_code"],
        "equipment_class": row["equipment_class"],
        "max_continuous_lpm": row["max_continuous_lpm"],
        "max_pulse_setting": row["max_pulse_setting"],
        "pm_interval_days": row["pm_interval_days"],
        "next_pm_due_date": iso_date(row["next_pm_due_date"]),
        "status": row["status"],
        "replaces_unit_id": row["replaces_unit_id"],
        "recall_remediated_at": iso(row["recall_remediated_at"]),
        "quarantine_reason": row["quarantine_reason"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def placement_out(row):
    return {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "equipment_unit_id": row["equipment_unit_id"],
        "role": row["role"],
        "status": row["status"],
        "placed_at": iso(row["placed_at"]),
        "removed_at": iso(row["removed_at"]),
        "removal_reason": row["removal_reason"],
        "malfunction_count": row["malfunction_count"],
        "last_symptom": row["last_symptom"],
        "last_severity_tier": row["last_severity_tier"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def route_out(row):
    return {
        "id": row["id"],
        "branch_id": row["branch_id"],
        "service_date": iso_date(row["service_date"]),
        "driver_user_id": row["driver_user_id"],
        "shift_start_utc": iso(row["shift_start_utc"]),
        "shift_end_utc": iso(row["shift_end_utc"]),
        "status": row["status"],
        "total_o2_liters_committed": row["total_o2_liters_committed"],
        "refill_slots_used": row["refill_slots_used"],
        "planned_stop_count": row["planned_stop_count"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def route_stop_out(row):
    return {
        "id": row["id"],
        "route_id": row["route_id"],
        "contract_id": row["contract_id"],
        "stop_type": row["stop_type"],
        "window_start_utc": iso(row["window_start_utc"]),
        "window_end_utc": iso(row["window_end_utc"]),
        "service_minutes": row["service_minutes"],
        "cylinders_requested": row["cylinders_requested"],
        "sequence_index": row["sequence_index"],
        "liters_committed": row["liters_committed"],
        "status": row["status"],
        "safety_result": row["safety_result"],
        "smoking_in_home": row["smoking_in_home"],
        "electrical_pass": row["electrical_pass"],
        "patient_teachback_score": row["patient_teachback_score"],
        "education_topics_covered": list(row["education_topics_covered"]),
        "safety_findings_count": row["safety_findings_count"],
        "completed_at": iso(row["completed_at"]),
        "completed_by_user_id": row["completed_by_user_id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def recall_notice_out(row):
    return {
        "id": row["id"],
        "model_code": row["model_code"],
        "severity": row["severity"],
        "issued_at": iso(row["issued_at"]),
        "remediation_deadline_utc": iso(row["remediation_deadline_utc"]),
        "status": row["status"],
        "affected_unit_count": row["affected_unit_count"],
        "auto_quarantined_unit_count": row["auto_quarantined_unit_count"],
        "remediated_unit_count": remediated_unit_count(row),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def travel_authorization_out(row):
    return {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "receiving_branch_id": row["receiving_branch_id"],
        "destination_altitude_feet": row["destination_altitude_feet"],
        "depart_utc": iso(row["depart_utc"]),
        "return_utc": iso(row["return_utc"]),
        "status": row["status"],
        "decided_by_user_id": row["decided_by_user_id"],
        "trip_hours": row["trip_hours"],
        "altitude_factor": num2(row["altitude_factor"]),
        "effective_lpm": num2(row["effective_lpm"]),
        "base_liters": row["base_liters"],
        "reserve_liters": row["reserve_liters"],
        "required_liters": row["required_liters"],
        "cylinders_raw": row["cylinders_raw"],
        "handling_surcharge_cylinders": row["handling_surcharge_cylinders"],
        "supply_cylinders_authorized": row["supply_cylinders_authorized"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }
