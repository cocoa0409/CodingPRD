"""Payload factories — one per entity, input fields only.

Each factory provides PRD-required input fields with sensible defaults and
accepts **overrides for the values a test needs to control. Only fields the PRD
marks as client input are included; system/computed fields are never sent.
"""


def create_agency_payload(**overrides) -> dict:
    payload = {"name": "Test Agency", "state_code": "CA", "caseload_cap": 50}
    payload.update(overrides)
    return payload


def create_clinic_payload(agency_id, **overrides) -> dict:
    payload = {"agency_id": agency_id, "name": "Test Clinic"}
    payload.update(overrides)
    return payload


def create_vendor_payload(agency_id, **overrides) -> dict:
    payload = {"agency_id": agency_id, "legal_name": "Test Vendor", "peer_group": "MEDIUM"}
    payload.update(overrides)
    return payload


def create_household_payload(agency_id, **overrides) -> dict:
    payload = {"agency_id": agency_id, "household_size": 3}
    payload.update(overrides)
    return payload


def create_participant_payload(household_id, **overrides) -> dict:
    payload = {
        "household_id": household_id,
        "full_name": "Test Participant",
        "ssn_last4": "0001",
        "category": "CHILD",
    }
    payload.update(overrides)
    return payload


def create_application_payload(participant_id, **overrides) -> dict:
    payload = {"participant_id": participant_id}
    payload.update(overrides)
    return payload


def create_income_record_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "gross_amount_cents": 100000,
        "pay_frequency": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def create_food_prescription_payload(certification_id, expected_participant_version, **overrides) -> dict:
    payload = {
        "certification_id": certification_id,
        "line_items": [{"food_category": "MILK", "requested_units": 4}],
        "expected_participant_version": expected_participant_version,
    }
    payload.update(overrides)
    return payload


def create_redemption_payload(ebt_account_id, vendor_id, **overrides) -> dict:
    payload = {
        "ebt_account_id": ebt_account_id,
        "vendor_id": vendor_id,
        "food_category": "MILK",
        "units": 1,
    }
    payload.update(overrides)
    return payload


def create_clinic_appointment_payload(clinic_id, participant_id, expected_clinic_version, **overrides) -> dict:
    payload = {
        "clinic_id": clinic_id,
        "participant_id": participant_id,
        "purpose": "INITIAL_CERT",
        "start_utc": "2026-03-10T10:00:00.000Z",
        "end_utc": "2026-03-10T10:30:00.000Z",
        "expected_clinic_version": expected_clinic_version,
    }
    payload.update(overrides)
    return payload


def create_peer_session_payload(participant_id, **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "peer_counselor_id": "pc-1",
        "start_utc": "2026-03-10T10:00:00.000Z",
        "end_utc": "2026-03-10T10:30:00.000Z",
    }
    payload.update(overrides)
    return payload
