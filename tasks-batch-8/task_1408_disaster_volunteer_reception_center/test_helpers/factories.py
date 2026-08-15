"""Payload factories — one per creatable resource, input fields only."""
from .constants import TEST_DEFAULTS


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "name": "Riverton Flood 2026",
        "ppe_stock": dict(TEST_DEFAULTS["PPE_STOCK"]),
    }
    defaults.update(overrides)
    if "ppe_stock" in overrides:
        defaults["ppe_stock"] = dict(overrides["ppe_stock"])
    return defaults


def create_volunteer_payload(incident_id: str, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "full_name": "Alex Avery",
        "phone": TEST_DEFAULTS["PHONE"],
        "email": TEST_DEFAULTS["EMAIL"],
        "home_locality": TEST_DEFAULTS["HOME_LOCALITY"],
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(volunteer_id: str, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "skill_code": TEST_DEFAULTS["SKILL"],
        "credential_class": TEST_DEFAULTS["CREDENTIAL_CLASS"],
        "expires_at": TEST_DEFAULTS["CREDENTIAL_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_background_check_payload(volunteer_id: str, **overrides) -> dict:
    defaults = {"volunteer_id": volunteer_id}
    defaults.update(overrides)
    return defaults


def create_clearance_payload(volunteer_id: str, clearance_type: str, **overrides) -> dict:
    defaults = {"volunteer_id": volunteer_id, "clearance_type": clearance_type}
    defaults.update(overrides)
    return defaults


def create_support_request_payload(incident_id: str, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "requesting_agency": TEST_DEFAULTS["AGENCY"],
        "site_name": TEST_DEFAULTS["SITE_NAME"],
        "required_skill": TEST_DEFAULTS["SKILL"],
        "min_credential_class": TEST_DEFAULTS["CREDENTIAL_CLASS"],
        "headcount_needed": 1,
        "criticality": "STANDARD",
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(incident_id: str, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "site_name": TEST_DEFAULTS["SITE_NAME"],
        "hazard_level": "GREEN",
        "start_at": TEST_DEFAULTS["SHIFT_START"],
        "end_at": TEST_DEFAULTS["SHIFT_END"],
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(volunteer_id: str, support_request_id: str,
                              site_shift_id: str, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "support_request_id": support_request_id,
        "site_shift_id": site_shift_id,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(incident_id: str, site_shift_id: str, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "site_shift_id": site_shift_id,
        "vehicle_id": "BUS-1",
        "seat_capacity": 20,
        "depart_at": "2026-08-10T07:00:00Z",
        "arrive_estimate_at": "2026-08-10T07:45:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_seat_booking_payload(trip_id: str, assignment_id: str, **overrides) -> dict:
    defaults = {"trip_id": trip_id, "assignment_id": assignment_id}
    defaults.update(overrides)
    return defaults


def create_ppe_issuance_payload(volunteer_id: str, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "item_type": "GLOVES",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_hour_entry_payload(assignment_id: str, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "work_date": TEST_DEFAULTS["WORK_DATE"],
        "hours": 8.0,
    }
    defaults.update(overrides)
    return defaults


def create_risk_report_payload(subject_volunteer_id: str, **overrides) -> dict:
    defaults = {
        "subject_volunteer_id": subject_volunteer_id,
        "severity": "LOW",
        "category": "OTHER",
        "description": "late arrival at staging area",
        "occurred_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
