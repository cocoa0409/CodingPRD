"""Payload factories — one per creatable resource, input fields only (PRD 4)."""
from typing import Any, Dict, List, Optional

from .constants import (
    STD_BOOKING_CLOSE_AT,
    STD_BOOKING_OPEN_AT,
    STD_BUFFER,
    STD_DAY,
    STD_SLOT_LENGTH,
    STD_TRAVEL,
)

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def unique_email(domain: str = "x.edu") -> str:
    return f"user{_next()}@{domain}"


def create_window_payload(**overrides) -> Dict[str, Any]:
    """Required fields plus the five optional policy knobs (defaults per PRD 3.1)."""
    defaults: Dict[str, Any] = {
        "name": "Fall Conferences",
        "term_label": "2026-FALL",
        "format": "ELEMENTARY",
        "slot_length_minutes": STD_SLOT_LENGTH,
        "buffer_minutes": STD_BUFFER,
        "travel_minutes": STD_TRAVEL,
        "day_windows": [dict(STD_DAY)],
        "booking_open_at": STD_BOOKING_OPEN_AT,
        "booking_close_at": STD_BOOKING_CLOSE_AT,
        "teacher_daily_conf_cap": 6,
        "family_conf_cap": 8,
        "cancel_cutoff_hours": 24,
        "waitlist_offer_ttl_hours": 24,
        "no_show_strike_threshold": 3,
        "auto_no_show_grace_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_teacher_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "full_name": f"Teacher {n}",
        "email": unique_email(),
        "grade_band": "ELEMENTARY",
        "subjects": [],
        "supports_in_person": True,
        "supports_virtual": False,
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "primary_guardian_name": f"Guardian {n}",
        "email": unique_email("x.com"),
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "full_name": f"Student {n}",
        "grade_level": 3,
    }
    defaults.update(overrides)
    return defaults


def create_teacher_link_payload(teacher_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"teacher_id": teacher_id}
    defaults.update(overrides)
    return defaults


def create_booking_payload(
    slot_id: str, student_id: str, channel: str = "IN_PERSON", **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "slot_id": slot_id,
        "student_id": student_id,
        "channel": channel,
    }
    defaults.update(overrides)
    return defaults


def create_interpreter_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "full_name": f"Interpreter {n}",
        "languages": ["es"],
        "max_consecutive_minutes": 120,
        "base_minutes_per_window": 600,
        "hourly_rate_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_interpreter_request_payload(
    booking_id: str, language: str = "es", **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"booking_id": booking_id, "language": language}
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(
    window_id: str,
    student_id: str,
    teacher_id: str,
    channel_pref: str = "EITHER",
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "window_id": window_id,
        "student_id": student_id,
        "teacher_id": teacher_id,
        "channel_pref": channel_pref,
    }
    defaults.update(overrides)
    return defaults


def create_outreach_task_payload(
    family_id: str, kind: str = "NO_SHOW_FOLLOW_UP", **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"family_id": family_id, "kind": kind}
    defaults.update(overrides)
    return defaults
