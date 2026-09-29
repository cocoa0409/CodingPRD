"""Resource representations. Every computed field is derived at serialization
time so a read never returns a stale figure (PRD 2.5)."""
import clock
import derive
from db import db

ts = clock.fmt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": ts(rec["created_at"]),
        "updated_at": ts(rec["updated_at"]),
        "version": rec["version"],
    }


def unit(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "hospital_type": rec["hospital_type"],
        "designated_level": rec["designated_level"],
        "designation_status": rec["designation_status"],
        "capability_level": derive.capability_level(rec),
        "effective_level": derive.effective_level(rec),
        "staffing_compliant": derive.staffing_compliant(rec),
        "equipment_compliant": derive.equipment_compliant(rec),
        "staffed_bed_target": rec["staffed_bed_target"],
        "escalation_bed_count": derive.escalation_bed_count(rec),
        "occupied_bed_count": derive.occupied_bed_count(rec),
        "held_bed_count": derive.held_bed_count(rec),
        "available_bed_count": derive.available_bed_count(rec),
        "census_posture": derive.census_posture(rec),
        "required_nurse_count": derive.required_nurse_count(rec),
        "transport_capable": rec["transport_capable"],
        "annual_admission_volume": rec["annual_admission_volume"],
        "followup_clinic_daily_capacity": rec["followup_clinic_daily_capacity"],
        "quality_flag": rec["quality_flag"],
        "deferral_queue_depth": derive.deferral_queue_depth(rec),
    })
    return out


def standard(rec):
    return {
        "id": rec["id"],
        "created_at": ts(rec["created_at"]),
        "level": rec["level"],
        "required_credential_codes": list(rec["required_credential_codes"]),
        "required_equipment_codes": list(rec["required_equipment_codes"]),
        "nurse_patient_ratio_denominator": rec["nurse_patient_ratio_denominator"],
        "min_annual_volume": rec["min_annual_volume"],
        "transport_capability_required": rec["transport_capability_required"],
        "min_compliance_score": rec["min_compliance_score"],
        "conditional_floor_score": rec["conditional_floor_score"],
    }


def credential(rec):
    out = _common(rec)
    out.update({
        "unit_id": rec["unit_id"],
        "credential_code": rec["credential_code"],
        "holder_reference": rec["holder_reference"],
        "fte": rec["fte"],
        "expires_on": ts(rec["expires_on"]),
        "revoked_at": ts(rec["revoked_at"]) if rec["revoked_at"] else None,
        "status": derive.credential_status(rec),
    })
    return out


def asset(rec):
    out = _common(rec)
    out.update({
        "unit_id": rec["unit_id"],
        "equipment_code": rec["equipment_code"],
        "asset_tag": rec["asset_tag"],
        "last_service_at": ts(rec["last_service_at"]),
        "service_interval_days": rec["service_interval_days"],
        "next_service_due_at": ts(derive.next_service_due_at(rec)),
        "out_of_service_at": ts(rec["out_of_service_at"]) if rec["out_of_service_at"] else None,
        "out_of_service_reason": rec["out_of_service_reason"],
        "status": derive.asset_status(rec),
        "decontamination_ready_at": (ts(rec["decontamination_ready_at"])
                                     if rec["decontamination_ready_at"] else None),
    })
    return out


def review(rec):
    out = _common(rec)
    out.update({
        "unit_id": rec["unit_id"],
        "requested_level": rec["requested_level"],
        "assigned_nurse_count": rec["assigned_nurse_count"],
        "status": rec["status"],
        "submission_round": rec["submission_round"],
        "assessment_at": ts(rec["assessment_at"]) if rec["assessment_at"] else None,
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "verified_by_user_id": rec["verified_by_user_id"],
        "certified_by_user_id": rec["certified_by_user_id"],
        "required_nurse_count": rec["required_nurse_count"],
        "staffing_subscore": rec["staffing_subscore"],
        "equipment_subscore": rec["equipment_subscore"],
        "volume_subscore": rec["volume_subscore"],
        "compliance_score": rec["compliance_score"],
        "outcome_level": rec["outcome_level"],
        "return_reason": rec["return_reason"],
        "denial_basis": rec["denial_basis"],
    })
    return out


def referral(rec):
    current, anticipated, basis = derive.referral_levels(rec)
    out = _common(rec)
    out.update({
        "referring_unit_id": rec["referring_unit_id"],
        "receiving_unit_id": rec["receiving_unit_id"],
        "source_admission_id": rec["source_admission_id"],
        "superseded_by_referral_id": rec["superseded_by_referral_id"],
        "referral_kind": rec["referral_kind"],
        "case_reference": rec["case_reference"],
        "gestational_age_weeks": rec["gestational_age_weeks"],
        "birth_weight_grams": rec["birth_weight_grams"],
        "weight_basis_grams": derive.weight_basis_grams(rec),
        "support_modality": rec["support_modality"],
        "diagnoses": list(rec["diagnoses"]),
        "planned_surgery": rec["planned_surgery"],
        "current_support_level": current,
        "anticipated_need_level": anticipated,
        "level_basis": basis,
        "required_level": anticipated,
        "maternal_transfer_preferred": derive.maternal_transfer_preferred(rec),
        "triage_priority": derive.triage_priority(rec),
        "status": rec["status"],
        "info_request_rounds": rec["info_request_rounds"],
        "requested_items": rec["requested_items"],
        "decision_reason": rec["decision_reason"],
        "reservation_id": derive.referral_reservation_id(rec),
    })
    return out


def reservation(rec):
    out = _common(rec)
    out.update({
        "unit_id": rec["unit_id"],
        "referral_id": rec["referral_id"],
        "bed_class": rec["bed_class"],
        "held_at": ts(rec["held_at"]),
        "expires_at": ts(rec["expires_at"]),
        "status": rec["status"],
        "released_reason": rec["released_reason"],
    })
    return out


def run(rec):
    out = _common(rec)
    out.update({
        "reservation_id": rec["reservation_id"],
        "receiving_unit_id": rec["receiving_unit_id"],
        "isolette_asset_id": rec["isolette_asset_id"],
        "mode": rec["mode"],
        "crew_composition": list(rec["crew_composition"]),
        "depart_at": ts(rec["depart_at"]),
        "planned_return_at": ts(rec["planned_return_at"]),
        "weather_minimums_met": rec["weather_minimums_met"],
        "status": rec["status"],
        "decontamination_minutes": rec["decontamination_minutes"],
        "temp_c": rec["temp_c"],
        "glucose_mg_dl": rec["glucose_mg_dl"],
        "mean_bp_mmhg": rec["mean_bp_mmhg"],
        "spo2_pct": rec["spo2_pct"],
        "stabilization_score": rec["stabilization_score"],
        "stabilization_bundle_complete": rec["stabilization_bundle_complete"],
        "arrived_at": ts(rec["arrived_at"]) if rec["arrived_at"] else None,
        "abort_reason": rec["abort_reason"],
    })
    return out


def admission(rec):
    out = _common(rec)
    out.update({
        "unit_id": rec["unit_id"],
        "referral_id": rec["referral_id"],
        "transport_run_id": rec["transport_run_id"],
        "back_transfer_source_admission_id": rec["back_transfer_source_admission_id"],
        "gestational_age_weeks": rec["gestational_age_weeks"],
        "birth_weight_grams": rec["birth_weight_grams"],
        "current_weight_grams": rec["current_weight_grams"],
        "support_modality": rec["support_modality"],
        "current_care_level": derive.current_care_level(rec),
        "care_status": rec["care_status"],
        "infection_status": rec["infection_status"],
        "infection_confirmed_at": (ts(rec["infection_confirmed_at"])
                                   if rec["infection_confirmed_at"] else None),
        "patient_days": rec["patient_days"],
        "central_line_days": rec["central_line_days"],
        "ventilator_days": rec["ventilator_days"],
        "developmental_round_count": rec["developmental_round_count"],
        "kangaroo_care_sessions": rec["kangaroo_care_sessions"],
        "family_presence_minutes": rec["family_presence_minutes"],
        "cluster_care_compliant_count": rec["cluster_care_compliant_count"],
        "light_cycling_compliant_count": rec["light_cycling_compliant_count"],
        "developmental_bundle_score": rec["developmental_bundle_score"],
        "milk_administered_ml": rec["milk_administered_ml"],
        "high_risk_graduate": rec["high_risk_graduate"],
        "back_transfer_attestation_note": rec["back_transfer_attestation_note"],
        "discharged_at": ts(rec["discharged_at"]) if rec["discharged_at"] else None,
        "discharge_disposition": rec["discharge_disposition"],
    })
    return out


def batch(rec):
    out = _common(rec)
    out.update({
        "admission_id": rec["admission_id"],
        "donor_type": rec["donor_type"],
        "volume_ml": rec["volume_ml"],
        "expressed_at": ts(rec["expressed_at"]),
        "expires_at": ts(rec["expires_at"]),
        "label_code": rec["label_code"],
        "received_by_user_id": rec["received_by_user_id"],
        "verified_by_user_id": rec["verified_by_user_id"],
        "administered_ml": rec["administered_ml"],
        "discarded_ml": rec["discarded_ml"],
        "remaining_ml": rec["remaining_ml"],
        "status": rec["status"],
        "pre_quarantine_status": rec["pre_quarantine_status"],
    })
    return out


def escalation(rec):
    out = _common(rec)
    out.update({
        "unit_id": rec["unit_id"],
        "requested_beds": rec["requested_beds"],
        "effective_from": ts(rec["effective_from"]),
        "effective_to": ts(rec["effective_to"]),
        "census_ratio_at_request": rec["census_ratio_at_request"],
        "escalation_tier": rec["escalation_tier"],
        "staffing_waiver_ratio": rec["staffing_waiver_ratio"],
        "authorized_beds": rec["authorized_beds"],
        "status": rec["status"],
        "authorized_by_user_id": rec["authorized_by_user_id"],
        "denial_reason": rec["denial_reason"],
    })
    return out


def report(rec):
    out = _common(rec)
    out.update({
        "unit_id": rec["unit_id"],
        "period_start": ts(rec["period_start"]),
        "period_end": ts(rec["period_end"]),
        "reported_patient_days": rec["reported_patient_days"],
        "reported_central_line_days": rec["reported_central_line_days"],
        "clabsi_count": rec["clabsi_count"],
        "mortality_count": rec["mortality_count"],
        "cohort_size": rec["cohort_size"],
        "birth_weight_risk_weight": rec["birth_weight_risk_weight"],
        "crude_clabsi_rate": rec["crude_clabsi_rate"],
        "device_adjusted_clabsi_rate": rec["device_adjusted_clabsi_rate"],
        "variant_applied": rec["variant_applied"],
        "data_completeness_flag": rec["data_completeness_flag"],
        "network_benchmark_flag": rec["network_benchmark_flag"],
        "status": rec["status"],
        "submitted_at": ts(rec["submitted_at"]) if rec["submitted_at"] else None,
        "rejection_reason": rec["rejection_reason"],
    })
    return out


def enrollment(rec):
    adm = db.admissions.get(rec["admission_id"])
    basis = derive.eligibility_basis(adm) if adm else "NOT_ELIGIBLE"
    out = _common(rec)
    out.update({
        "admission_id": rec["admission_id"],
        "clinic_unit_id": rec["clinic_unit_id"],
        "target_appointment_date": ts(rec["target_appointment_date"]),
        "confirmed_appointment_date": (ts(rec["confirmed_appointment_date"])
                                       if rec["confirmed_appointment_date"] else None),
        "appointment_window_start": ts(rec["appointment_window_start"]),
        "appointment_window_end": ts(rec["appointment_window_end"]),
        "eligibility_basis": basis,
        "risk_tier": derive.risk_tier(adm, basis) if adm else "MODERATE",
        "status": rec["status"],
        "attendance_recorded_at": (ts(rec["attendance_recorded_at"])
                                   if rec["attendance_recorded_at"] else None),
    })
    return out
