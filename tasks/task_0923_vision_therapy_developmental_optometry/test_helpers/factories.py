"""Payload factories — one per entity, input fields only."""

from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "PATIENT_NAME": "Ana Ruiz",
    "PATIENT_DOB": "2016-06-01",
    "DIAGNOSIS": "CONVERGENCE_INSUFFICIENCY",
    "MEDICAL_PAYER_NAME": "Meridian Medical",
    "VISION_PAYER_NAME": "ClearSight Vision",
    "MEMBER_NUMBER": "M-1001",
    "AUTH_NUMBER": "A-9001",
    "ENCOUNTER_DATE": "2026-06-01",
    "COVERAGE_START": "2026-01-01",
    "COVERAGE_END": "2026-12-31",
    "WINDOW_START": "2026-06-01",
    "WINDOW_END": "2026-12-01",
}


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["PATIENT_DOB"],
        "diagnosis_category": DEFAULTS["DIAGNOSIS"],
    }
    payload.update(overrides)
    return payload


def create_medical_payer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MEDICAL_PAYER_NAME"],
        "payer_type": "MEDICAL",
        "allowed_amount_timed_unit": 34.00,
        "allowed_amount_flat_session": 120.00,
        "allowed_amount_evaluation": 165.00,
        "coinsurance_rate": 0.20,
        "frequency_limit_months": 12,
    }
    payload.update(overrides)
    return payload


def create_vision_payer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["VISION_PAYER_NAME"],
        "payer_type": "VISION",
        "allowed_amount_timed_unit": 0.00,
        "allowed_amount_flat_session": 0.00,
        "allowed_amount_evaluation": 0.00,
        "coinsurance_rate": 0.00,
        "frequency_limit_months": 12,
    }
    payload.update(overrides)
    return payload


def create_coverage_payload(patient_id: str, payer_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "payer_id": payer_id,
        "member_number": DEFAULTS["MEMBER_NUMBER"],
        "effective_start_date": DEFAULTS["COVERAGE_START"],
        "effective_end_date": DEFAULTS["COVERAGE_END"],
    }
    payload.update(overrides)
    return payload


def create_authorization_payload(patient_id: str, coverage_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "coverage_id": coverage_id,
        "auth_number": DEFAULTS["AUTH_NUMBER"],
        "visits_authorized": 12,
        "window_start_date": DEFAULTS["WINDOW_START"],
        "window_end_date": DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_therapist_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dr Lee",
        "credential": "OPTOMETRIST",
        "credential_expires_at": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_room_payload(**overrides) -> dict:
    payload = {"name": "Room A", "equipment_class": "STANDARD"}
    payload.update(overrides)
    return payload


def create_assessment_payload(patient_id: str, performed_by_therapist_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "assessment_type": "EVALUATION",
        "purpose": "DIAGNOSTIC",
        "encounter_date": DEFAULTS["ENCOUNTER_DATE"],
        "performed_by_therapist_id": performed_by_therapist_id,
    }
    payload.update(overrides)
    return payload


def npc_measurement_payload(break_cm=12.0, recovery_cm=16.0, **overrides) -> dict:
    payload = {
        "metric_code": "NPC",
        "eye": "OU",
        "npc_break_cm": break_cm,
        "npc_recovery_cm": recovery_cm,
    }
    payload.update(overrides)
    return payload


def amplitude_measurement_payload(amplitude_d=8.0, **overrides) -> dict:
    payload = {
        "metric_code": "ACCOMMODATIVE_AMPLITUDE",
        "eye": "OU",
        "amplitude_d": amplitude_d,
    }
    payload.update(overrides)
    return payload


def vergence_measurement_payload(vergence_bo_break_pd=8.0, **overrides) -> dict:
    payload = {
        "metric_code": "VERGENCE_BASE_OUT",
        "eye": "OU",
        "vergence_bo_break_pd": vergence_bo_break_pd,
    }
    payload.update(overrides)
    return payload


def acuity_measurement_payload(acuity_logmar=0.30, **overrides) -> dict:
    payload = {
        "metric_code": "VISUAL_ACUITY",
        "eye": "OD",
        "acuity_logmar": acuity_logmar,
    }
    payload.update(overrides)
    return payload


def symptom_measurement_payload(ciss_score=34, **overrides) -> dict:
    payload = {
        "metric_code": "SYMPTOM_SURVEY",
        "eye": "OU",
        "ciss_score": ciss_score,
    }
    payload.update(overrides)
    return payload


def create_plan_payload(patient_id: str, source_assessment_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "source_assessment_id": source_assessment_id,
        "discharge_criteria_mode": "METRIC",
        "prescribed_home_sessions_per_week": 1,
    }
    payload.update(overrides)
    return payload


def create_phase_payload(sequence_index: int = 1, **overrides) -> dict:
    payload = {
        "sequence_index": sequence_index,
        "name": f"Phase {sequence_index}",
        "required_mastery_count": 2,
    }
    payload.update(overrides)
    return payload


def create_session_payload(
    therapist_id: str,
    room_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    expected_authorization_version: int,
    **overrides,
) -> dict:
    payload = {
        "therapist_id": therapist_id,
        "room_id": room_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "procedure_code": "TIMED_THERAPEUTIC_ACTIVITY",
        "expected_authorization_version": expected_authorization_version,
    }
    payload.update(overrides)
    return payload


def create_home_session_payload(performed_at: str, timed_minutes: int, **overrides) -> dict:
    payload = {"performed_at": performed_at, "timed_minutes": timed_minutes}
    payload.update(overrides)
    return payload


def complete_session_payload(performed_at: str, timed_minutes: int, **overrides) -> dict:
    payload = {"performed_at": performed_at, "timed_minutes": timed_minutes}
    payload.update(overrides)
    return payload


def create_kit_item_payload(**overrides) -> dict:
    payload = {
        "name": "Vectogram set",
        "item_class": "LOANABLE_SERIALIZED",
        "replacement_cost": 275.00,
        "useful_life_months": 24,
        "in_service_date": "2025-11-01",
        "initial_qty": 2,
    }
    payload.update(overrides)
    return payload


def create_kit_loan_payload(kit_item_id: str, patient_id: str, plan_id: str, **overrides) -> dict:
    payload = {
        "kit_item_id": kit_item_id,
        "patient_id": patient_id,
        "plan_id": plan_id,
        "quantity": 1,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(
    patient_id: str,
    coverage_id: str,
    service_class: str,
    service_date: str,
    expected_coverage_version: int,
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "coverage_id": coverage_id,
        "service_class": service_class,
        "service_date": service_date,
        "expected_coverage_version": expected_coverage_version,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "direction": "OUTBOUND",
        "urgency": "ROUTINE",
        "referring_provider_name": "Vision Therapy Clinic",
        "target_provider_name": "Regional Paediatric Ophthalmology",
        "reason": "Care transfer",
    }
    payload.update(overrides)
    return payload


def create_occlusion_payload(patient_id: str, source_assessment_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "source_assessment_id": source_assessment_id,
        "severity": "MODERATE",
        "baseline_acuity_logmar": 0.40,
    }
    payload.update(overrides)
    return payload
