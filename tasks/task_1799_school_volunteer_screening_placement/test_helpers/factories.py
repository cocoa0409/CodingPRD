"""Payload factories — one per entity, input fields only."""
from uuid import uuid4

from .constants import (
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    DEFAULT_WORKED_DATE,
)


def _unique_email() -> str:
    return f"vol-{uuid4().hex[:10]}@example.org"


def create_campus_payload(**overrides) -> dict:
    suffix = uuid4().hex[:6].upper()
    defaults = {
        "name": "Lincoln Elementary",
        "campus_code": f"C{suffix[:5]}",
        "badge_prefix": f"B{suffix[:5]}",
    }
    defaults.update(overrides)
    return defaults


def create_lincoln_campus_payload(**overrides) -> dict:
    """The canonical LNC campus used by badge-code scenarios."""
    defaults = {
        "name": "Lincoln Elementary",
        "campus_code": "LNC",
        "badge_prefix": "LNC",
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Volunteer",
        "email": _unique_email(),
        "contact_type": "SUPERVISED",
    }
    defaults.update(overrides)
    return defaults


def create_background_check_payload(volunteer_id, expected_volunteer_version,
                                    level="BASIC", **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "level": level,
        "expected_volunteer_version": expected_volunteer_version,
    }
    defaults.update(overrides)
    return defaults


def adjudicate_check_payload(findings="NONE", **overrides) -> dict:
    defaults = {"findings": findings}
    defaults.update(overrides)
    return defaults


def create_training_module_payload(**overrides) -> dict:
    defaults = {
        "module_code": f"M{uuid4().hex[:6].upper()}",
        "title": "Volunteer Orientation",
        "required_contact_types": ["SUPERVISED", "UNSUPERVISED"],
        "validity_days": 365,
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(volunteer_id, module_id,
                                   completed_at="2026-07-01T00:00:00Z",
                                   **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "module_id": module_id,
        "completed_at": completed_at,
    }
    defaults.update(overrides)
    return defaults


def create_opportunity_payload(campus_id, **overrides) -> dict:
    defaults = {
        "campus_id": campus_id,
        "title": "Library Help",
        "required_contact_type": "SUPERVISED",
        "restricted_category": "NONE",
        "capacity": 2,
        "starts_at": DEFAULT_WINDOW_START,
        "ends_at": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(opportunity_id, **overrides) -> dict:
    defaults = {"opportunity_id": opportunity_id}
    defaults.update(overrides)
    return defaults


def create_hour_entry_payload(placement_id, **overrides) -> dict:
    defaults = {
        "placement_id": placement_id,
        "worked_date": DEFAULT_WORKED_DATE,
        "hours": 2.0,
        "activity_category": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(campus_id, **overrides) -> dict:
    defaults = {"campus_id": campus_id}
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(volunteer_id, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "severity": "LOW",
        "description": "Incident narrative",
    }
    defaults.update(overrides)
    return defaults


def adjudicate_incident_payload(outcome="UNFOUNDED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_recognition_award_payload(volunteer_id, tier,
                                     expected_volunteer_version,
                                     **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "tier": tier,
        "note": "",
        "expected_volunteer_version": expected_volunteer_version,
    }
    defaults.update(overrides)
    return defaults
