"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_AGE_GROUP,
    DEFAULT_BIRTH_DATE,
    DEFAULT_COURSE,
    DEFAULT_ENTRY_DEADLINE_UTC,
    DEFAULT_GENDER,
    DEFAULT_SESSION_DATE,
    DEFAULT_START_DATE,
)


def create_meet_payload(**overrides) -> dict:
    defaults = {
        "meet_name": "Test Meet",
        "course": DEFAULT_COURSE,
        "start_date": DEFAULT_START_DATE,
        "entry_deadline_utc": DEFAULT_ENTRY_DEADLINE_UTC,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(meet_id, **overrides) -> dict:
    defaults = {
        "meet_id": meet_id,
        "team_code": "AAA",
        "team_name": "Aquatics",
    }
    defaults.update(overrides)
    return defaults


def create_swimmer_payload(team_id, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "full_name": "Test Swimmer",
        "birth_date": DEFAULT_BIRTH_DATE,
        "gender": DEFAULT_GENDER,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(meet_id, **overrides) -> dict:
    defaults = {
        "meet_id": meet_id,
        "event_number": 1,
        "gender": DEFAULT_GENDER,
        "age_group": DEFAULT_AGE_GROUP,
        "stroke": "FREESTYLE",
        "distance_meters": 50,
        "is_relay": False,
        "session_date": DEFAULT_SESSION_DATE,
        "scheduled_start_minute": 540,
        "scheduled_end_minute": 570,
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(event_id, swimmer_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "swimmer_id": swimmer_id,
    }
    defaults.update(overrides)
    return defaults


def create_relay_team_payload(team_id, event_id, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "event_id": event_id,
        "relay_name": "A",
    }
    defaults.update(overrides)
    return defaults


def create_relay_leg_payload(leg_number, swimmer_id) -> dict:
    return {"leg_number": leg_number, "swimmer_id": swimmer_id}


def readings_payload(pad_cs=None, backup1_cs=None, backup2_cs=None,
                     watch_cs=None, pad_status=None) -> dict:
    payload: dict = {}
    if pad_cs is not None:
        payload["pad_cs"] = pad_cs
    if backup1_cs is not None:
        payload["backup1_cs"] = backup1_cs
    if backup2_cs is not None:
        payload["backup2_cs"] = backup2_cs
    if watch_cs is not None:
        payload["watch_cs"] = watch_cs
    if pad_status is not None:
        payload["pad_status"] = pad_status
    return payload


def create_official_payload(meet_id, **overrides) -> dict:
    defaults = {
        "meet_id": meet_id,
        "full_name": "Test Official",
        "lsc_membership_id": "LSC-001",
        "certifications": ["REFEREE"],
        "certification_expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_official_assignment_payload(official_id, role_on_deck) -> dict:
    return {"official_id": official_id, "role_on_deck": role_on_deck}


def create_disqualification_payload(**overrides) -> dict:
    defaults = {
        "dq_code": "FALSE_START",
        "call_notes": "call from deck",
    }
    defaults.update(overrides)
    return defaults


def create_standing_record_payload(**overrides) -> dict:
    defaults = {
        "record_time_cs": 2450,
        "holder_name": "Old Record Holder",
        "holder_team": "OLD",
        "set_on_date": "2025-06-01",
    }
    defaults.update(overrides)
    return defaults
