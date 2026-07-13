"""Payload factories — one per entity, input fields only.

Each factory builds a minimal valid create body; pass **overrides to control any field.
Only fields the client actually supplies (source: input) appear here.
"""
from .constants import TEST_DEFAULTS


def create_client_payload(full_name="Test Client", dob="1990-01-01", **overrides) -> dict:
    """POST /clients. Required: full_name, dob. Optional: ssn_last4, household_size,
    months_homeless, chronic_homeless (all defaulted server-side)."""
    payload = {"full_name": full_name, "dob": dob}
    payload.update(overrides)
    return payload


def create_assessment_payload(client_id, self_report_points=9, **overrides) -> dict:
    """POST /assessments. Required: client_id, self_report_points. Optional: tool,
    verification_delta."""
    payload = {"client_id": client_id, "self_report_points": self_report_points}
    payload.update(overrides)
    return payload


def create_consent_payload(client_id, scope=TEST_DEFAULTS["CONSENT_SCOPE"],
                           effective_date=TEST_DEFAULTS["EFFECTIVE_DATE"],
                           expiry_date=TEST_DEFAULTS["EXPIRY_DATE"], **overrides) -> dict:
    """POST /consents. Required: client_id, scope, effective_date, expiry_date."""
    payload = {"client_id": client_id, "scope": scope,
               "effective_date": effective_date, "expiry_date": expiry_date}
    payload.update(overrides)
    return payload


def create_screening_payload(client_id, has_safe_alternative=False, **overrides) -> dict:
    """POST /screenings. Required: client_id, has_safe_alternative. Optional: is_fleeing_dv."""
    payload = {"client_id": client_id, "has_safe_alternative": has_safe_alternative}
    payload.update(overrides)
    return payload


def create_shelter_payload(name="Test Shelter", project_type=TEST_DEFAULTS["PROJECT_TYPE"],
                           **overrides) -> dict:
    """POST /shelters. Required: name, project_type."""
    payload = {"name": name, "project_type": project_type}
    payload.update(overrides)
    return payload


def create_bed_payload(shelter_id, label="B1", **overrides) -> dict:
    """POST /beds. Required: shelter_id, label."""
    payload = {"shelter_id": shelter_id, "label": label}
    payload.update(overrides)
    return payload


def create_bed_reservation_payload(client_id, shelter_id, entry_date, expected_exit_date,
                                   expected_shelter_version, **overrides) -> dict:
    """POST /bed-reservations. Required: client_id, shelter_id, entry_date,
    expected_exit_date, expected_shelter_version."""
    payload = {
        "client_id": client_id,
        "shelter_id": shelter_id,
        "entry_date": entry_date,
        "expected_exit_date": expected_exit_date,
        "expected_shelter_version": expected_shelter_version,
    }
    payload.update(overrides)
    return payload


def create_waitlist_entry_payload(shelter_id, client_id, entry_date, expected_exit_date,
                                  **overrides) -> dict:
    """POST /waitlist-entries. Required: shelter_id, client_id, entry_date, expected_exit_date."""
    payload = {
        "shelter_id": shelter_id,
        "client_id": client_id,
        "entry_date": entry_date,
        "expected_exit_date": expected_exit_date,
    }
    payload.update(overrides)
    return payload


def create_prioritization_entry_payload(client_id, **overrides) -> dict:
    """POST /prioritization-entries. Required: client_id."""
    payload = {"client_id": client_id}
    payload.update(overrides)
    return payload


def create_housing_navigator_payload(name="Test Navigator", max_caseload=2, **overrides) -> dict:
    """POST /housing-navigators. Required: name, max_caseload."""
    payload = {"name": name, "max_caseload": max_caseload}
    payload.update(overrides)
    return payload


def create_referral_payload(client_id, prioritization_entry_id, navigator_id,
                            psh_project_name=TEST_DEFAULTS["PSH_PROJECT"], **overrides) -> dict:
    """POST /referrals. Required: client_id, prioritization_entry_id, navigator_id,
    psh_project_name."""
    payload = {
        "client_id": client_id,
        "prioritization_entry_id": prioritization_entry_id,
        "navigator_id": navigator_id,
        "psh_project_name": psh_project_name,
    }
    payload.update(overrides)
    return payload


def create_exit_record_payload(client_id, destination, reservation_id=None,
                               referral_id=None, **overrides) -> dict:
    """POST /exit-records. Required: client_id, destination, and exactly one of
    reservation_id (shelter exit) / referral_id (PSH exit)."""
    payload = {"client_id": client_id, "destination": destination}
    if reservation_id is not None:
        payload["reservation_id"] = reservation_id
    if referral_id is not None:
        payload["referral_id"] = referral_id
    payload.update(overrides)
    return payload
