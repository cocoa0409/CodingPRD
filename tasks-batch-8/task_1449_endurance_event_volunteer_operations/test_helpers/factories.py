"""Payload factories — one per entity, input fields only (PRD §3).

The standard event window (PRD §2.4 clock-driven tests) is shared:
race day 2026-10-04 06:00-22:00 UTC, early access 2026-08-10,
general signup 2026-08-17, signup closes 2026-09-27.
"""
from . import constants as C


def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "City Marathon",
        "event_start_at": C.EVENT_START,
        "event_end_at": C.EVENT_END,
        "early_access_opens_at": C.EARLY_ACCESS_OPENS,
        "signup_opens_at": C.SIGNUP_OPENS,
        "signup_closes_at": C.SIGNUP_CLOSES,
    }
    defaults.update(overrides)
    return defaults


def create_course_segment_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "segment_code": "SEG-A",
        "mile_start": 5,
        "mile_end": 10,
        "terrain_type": "ROAD",
    }
    defaults.update(overrides)
    return defaults


def create_role_catalog_entry_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "role_code": "MARSHAL",
        "title": "Course Marshal",
        "min_age_years": 16,
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(event_id, role_entry_id, segment_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "role_entry_id": role_entry_id,
        "segment_id": segment_id,
        "start_at": "2026-10-04T07:00:00Z",
        "end_at": "2026-10-04T11:00:00Z",
        "required_headcount": 1,
    }
    defaults.update(overrides)
    return defaults


def create_fundraising_group_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "name": "Track Club",
        "charity_code": "CHARITY-TC",
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "full_name": "V One",
        "date_of_birth": "2000-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(event_id, volunteer_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "volunteer_id": volunteer_id,
        "module_code": "SAFETY_BRIEFING",
    }
    defaults.update(overrides)
    return defaults


def create_signup_payload(volunteer_id, shift_id, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "shift_id": shift_id,
    }
    defaults.update(overrides)
    return defaults


def create_supply_inventory_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "item_code": "SAFETY_VEST",
        "description": "Vest",
        "quantity_total": 1,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_record_payload(signup_id, kind, **overrides) -> dict:
    defaults = {
        "signup_id": signup_id,
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults


def create_debrief_report_payload(event_id, shift_id, author_volunteer_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "shift_id": shift_id,
        "author_volunteer_id": author_volunteer_id,
        "headcount_actual": 1,
        "role_effectiveness_rating": 3,
    }
    defaults.update(overrides)
    return defaults


def create_role_adjustment_payload(event_id, role_entry_id, debrief_report_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "role_entry_id": role_entry_id,
        "debrief_report_id": debrief_report_id,
    }
    defaults.update(overrides)
    return defaults
