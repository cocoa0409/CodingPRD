"""Payload factories — one per entity, input fields only."""


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1945-01-01",
        "insurance_member_id": "MEM-TEST-01",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "referral_source": "Dr PCP",
        "reason": "recurrent falls",
    }
    defaults.update(overrides)
    return defaults


def create_clinician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Test",
        "discipline": "PT",
        "npi": "1234567890",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": "Balance Gym",
        "room_type": "BALANCE_GYM",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(patient_id: str, referral_id: str, clinician_id: str,
                              **overrides) -> dict:
    """High-risk defaults (gait 0.55 / tug 14.0 / berg 18 / meds 5 / falls 2 ->
    clinical_score 110, HIGH). Override the measured fields for other tiers."""
    defaults = {
        "patient_id": patient_id,
        "referral_id": referral_id,
        "clinician_id": clinician_id,
        "gait_speed_m_s": 0.55,
        "tug_seconds": 14.0,
        "berg_balance_score": 18,
        "medication_count": 5,
        "self_report_fall_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(patient_id: str, assessment_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "assessment_id": assessment_id,
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(patient_id: str, care_plan_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "care_plan_id": care_plan_id,
        "payer_name": "Medicare",
        "visits_authorized": 5,
        "allowed_amount_cents": 15000,
        "coinsurance_pct": 0.20,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(care_plan_id: str, clinician_id: str, room_id: str,
                           authorization_id: str, **overrides) -> dict:
    defaults = {
        "care_plan_id": care_plan_id,
        "clinician_id": clinician_id,
        "room_id": room_id,
        "authorization_id": authorization_id,
        "scheduled_start": "2026-06-01T10:00:00Z",
        "scheduled_end": "2026-06-01T11:00:00Z",
        "cpt_code": "97116",
    }
    defaults.update(overrides)
    return defaults


def create_home_safety_payload(patient_id: str, care_plan_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "care_plan_id": care_plan_id,
        "loose_rugs": 0,
        "poor_lighting_rooms": 0,
        "missing_grab_bars": 0,
        "unsecured_stairs": 0,
        "clutter_pathways": 0,
    }
    defaults.update(overrides)
    return defaults


def create_device_referral_payload(patient_id: str, care_plan_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "care_plan_id": care_plan_id,
        "device_type": "CANE",
    }
    defaults.update(overrides)
    return defaults


def create_reassessment_payload(clinician_id: str, **overrides) -> dict:
    """Low-risk defaults (gait 1.20 / tug 8.0 / berg 55 / meds 0 / falls 0 ->
    clinical_score 0, LOW)."""
    defaults = {
        "clinician_id": clinician_id,
        "gait_speed_m_s": 1.20,
        "tug_seconds": 8.0,
        "berg_balance_score": 55,
        "medication_count": 0,
        "self_report_fall_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_community_linkage_payload(patient_id: str, care_plan_id: str,
                                     assessment_id: str, expected_care_plan_version: int,
                                     **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "care_plan_id": care_plan_id,
        "assessment_id": assessment_id,
        "program_name": "MATTER_OF_BALANCE",
        "expected_care_plan_version": expected_care_plan_version,
    }
    defaults.update(overrides)
    return defaults
