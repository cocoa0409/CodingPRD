"""Payload factories — one per creation route, input fields only."""

from .constants import TEST_DEFAULTS


def create_establishment_payload(**overrides) -> dict:
    payload = {
        "name": "Test Body Art Studio",
        "street_address": "1 Test Street",
        "county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "establishment_type": "TATTOO",
    }
    payload.update(overrides)
    return payload


def create_artist_payload(establishment_id: str, **overrides) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "legal_name": "Test Practitioner",
    }
    payload.update(overrides)
    return payload


def bbp_training_payload(completed_on: str = None, **overrides) -> dict:
    payload = {"completed_on": completed_on or TEST_DEFAULTS["BBP_COMPLETED_ON"]}
    payload.update(overrides)
    return payload


def create_plan_review_payload(establishment_id: str, **overrides) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "floor_plan_reference": "FP-001",
        "sterilization_area_sqft": 60,
        "procedure_station_count": 2,
        "has_handwash_sink": True,
    }
    payload.update(overrides)
    return payload


def plan_review_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision, "decision_notes": "Recorded by the examiner."}
    payload.update(overrides)
    return payload


def resubmit_plan_review_payload(**overrides) -> dict:
    payload = {
        "floor_plan_reference": "FP-002",
        "sterilization_area_sqft": 60,
        "procedure_station_count": 2,
        "has_handwash_sink": True,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(
    establishment_id: str,
    inspection_type: str = "ROUTINE",
    scheduled_start_at: str = "2026-05-05T00:00:00Z",
    scheduled_end_at: str = "2026-05-05T02:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "inspection_type": inspection_type,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def create_violation_payload(
    violation_code: str = "STER_004",
    severity: str = "NONCRITICAL",
    narrative: str = "Autoclave log gap.",
    **overrides,
) -> dict:
    payload = {
        "violation_code": violation_code,
        "severity": severity,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def create_sterilization_record_payload(
    establishment_id: str,
    cycle_completed_at: str = "2026-04-20T00:00:00Z",
    spore_test_result: str = "PASS",
    **overrides,
) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "device_serial": "AC-1",
        "cycle_completed_at": cycle_completed_at,
        "spore_test_result": spore_test_result,
    }
    payload.update(overrides)
    return payload


def create_minor_consent_payload(establishment_id: str, **overrides) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "minor_full_name": "Minor Client",
        "minor_age_at_signing": 16,
        "guardian_full_name": "Guardian Client",
        "guardian_id_document_type": "DRIVERS_LICENSE",
        "guardian_id_document_number": "DL-1000",
        "authorized_procedure_type": "TATTOO",
        "consent_signed_at": "2026-05-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_procedure_log_payload(
    establishment_id: str,
    artist_id: str,
    client_age: int = 30,
    started_at: str = "2026-05-01T09:00:00Z",
    ended_at: str = "2026-05-01T10:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "artist_id": artist_id,
        "client_age": client_age,
        "procedure_type": "TATTOO",
        "started_at": started_at,
        "ended_at": ended_at,
        "aftercare_provided": True,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(establishment_id: str, **overrides) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "complainant_contact": "citizen@example.com",
        "category": "SANITATION",
        "narrative": "Floor was visibly dirty during my session.",
    }
    payload.update(overrides)
    return payload


def create_infection_report_payload(establishment_id: str, **overrides) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "reporter_contact": "patient@example.com",
        "infection_type": "MRSA",
        "procedure_date": "2026-04-20T00:00:00Z",
        "symptom_onset_at": "2026-04-25T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_enforcement_action_payload(
    action_type: str = "SUSPENSION",
    reason_code: str = "IMMINENT_HEALTH_HAZARD",
    **overrides,
) -> dict:
    payload = {"action_type": action_type, "reason_code": reason_code}
    payload.update(overrides)
    return payload


def create_renewal_application_payload(
    establishment_id: str, expected_establishment_version: int, **overrides
) -> dict:
    payload = {
        "establishment_id": establishment_id,
        "requested_term_start_on": "2027-05-01T00:00:00Z",
        "attested_bbp_current": True,
        "attested_sterilization_logs_complete": True,
        "expedite_requested": False,
        "expected_establishment_version": expected_establishment_version,
    }
    payload.update(overrides)
    return payload
