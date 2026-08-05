"""Payload factories — one per entity, input fields only."""
import random
import uuid


def unique_mrn() -> str:
    return f"MRN-{uuid.uuid4().hex[:10].upper()}"


def unique_npi() -> str:
    return str(random.randint(1000000000, 9999999999))


def create_patient_payload(**overrides) -> dict:
    payload = {
        "mrn": unique_mrn(),
        "full_name": "Test Patient",
        "date_of_birth": "1959-03-15",
    }
    payload.update(overrides)
    return payload


def create_physician_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dr Referring",
        "npi": unique_npi(),
    }
    payload.update(overrides)
    return payload


def create_clinician_payload(**overrides) -> dict:
    payload = {
        "full_name": "Exercise Physiologist",
        "credential": "EP",
    }
    payload.update(overrides)
    return payload


def create_station_payload(**overrides) -> dict:
    payload = {
        "name": "Treadmill-1",
        "station_type": "TELEMETRY",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id, physician_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "physician_id": physician_id,
        "program_type": "CARDIAC",
        "indication": "post-MI",
        "risk_stratification": "MODERATE",
    }
    payload.update(overrides)
    return payload


def create_program_payload(referral_id, **overrides) -> dict:
    payload = {"referral_id": referral_id}
    payload.update(overrides)
    return payload


def create_authorization_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "payer_name": "Acme Health",
        "authorized_visits": 10,
        "allowed_amount_cents": 18000,
        "copay_cents": 2000,
    }
    payload.update(overrides)
    return payload


def create_session_payload(program_id, clinician_id, station_id, expected_program_version, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "clinician_id": clinician_id,
        "station_id": station_id,
        "session_type": "MONITORED_EXERCISE",
        "phase": "PHASE_II",
        "scheduled_start": "2026-05-04T09:00:00Z",
        "scheduled_end": "2026-05-04T10:00:00Z",
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def create_care_plan_item_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "item_type": "GOAL",
        "title": "Walk 400m",
    }
    payload.update(overrides)
    return payload


def create_outcome_payload(program_id, timing, distance_meters, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "timing": timing,
        "distance_meters": distance_meters,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(program_id, session_id, authorization_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "session_id": session_id,
        "authorization_id": authorization_id,
    }
    payload.update(overrides)
    return payload
