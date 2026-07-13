"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_PROGRAM


def create_payer_payload(**overrides) -> dict:
    payload = {"name": "BlueMIH", "payer_type": "MEDICAID"}
    payload.update(overrides)
    return payload


def create_program_payload(payer_id, **overrides) -> dict:
    payload = {"name": "Pilot", "payer_id": payer_id}
    payload.update(DEFAULT_PROGRAM)
    payload.update(overrides)
    return payload


def create_provider_payload(provider_type, full_name=None, npi="1000000000", **overrides) -> dict:
    payload = {
        "full_name": full_name or f"{provider_type.title()} Staff",
        "provider_type": provider_type,
        "npi": npi,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Patient",
        "date_of_birth": "1960-01-01",
        "baseline_ed_visits_12mo": 4,
        "chronic_conditions_count": 1,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id, program_id, referring_source="ED", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "program_id": program_id,
        "referring_source": referring_source,
    }
    payload.update(overrides)
    return payload


def create_care_plan_payload(authoring_clinician_id, expected_enrollment_version,
                             risk_level="MODERATE", goals="reduce ED", **overrides) -> dict:
    payload = {
        "risk_level": risk_level,
        "authoring_clinician_id": authoring_clinician_id,
        "goals": goals,
        "expected_enrollment_version": expected_enrollment_version,
    }
    payload.update(overrides)
    return payload


def create_home_visit_payload(enrollment_id, care_plan_id, provider_id,
                              scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "care_plan_id": care_plan_id,
        "provider_id": provider_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_telehealth_payload(enrollment_id, patient_id, provider_id,
                              scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "patient_id": patient_id,
        "provider_id": provider_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def vitals_payload(systolic_bp=130, diastolic_bp=80, heart_rate=72) -> dict:
    return {"systolic_bp": systolic_bp, "diastolic_bp": diastolic_bp, "heart_rate": heart_rate}


def create_med_reconciliation_payload(enrollment_id, home_visit_id,
                                      medications=None, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "home_visit_id": home_visit_id,
        "medications": medications if medications is not None else ["lisinopril"],
    }
    payload.update(overrides)
    return payload


def create_social_referral_payload(enrollment_id, domain="HOUSING", **overrides) -> dict:
    payload = {"enrollment_id": enrollment_id, "domain": domain}
    payload.update(overrides)
    return payload


def create_ed_event_payload(patient_id, event_type, event_date, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "event_type": event_type,
        "event_date": event_date,
    }
    payload.update(overrides)
    return payload


def create_billing_claim_payload(enrollment_id, program_id, payer_id,
                                 period_start="2026-03-01T00:00:00Z",
                                 period_end="2026-04-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "program_id": program_id,
        "payer_id": payer_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload
