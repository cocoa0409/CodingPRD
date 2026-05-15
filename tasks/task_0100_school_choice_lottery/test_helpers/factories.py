"""Payload factories — one per endpoint that accepts a body, input
fields only.

The PRD §4 endpoint table is the authoritative source for input fields.
Each factory emits exactly the fields PRD describes as input; computed
fields (priority_category, lottery_weight, lottery_score, seats_offered,
seats_accepted, window_status, head_household_application_id,
waitlist_position, offer_expires_at, capacity_units_held) are NEVER
emitted from a factory — they are computed by the server per PRD §3.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def iso_utc(dt: datetime) -> str:
    """Format a datetime as PRD §2.4 ISO 8601 UTC with three fractional
    digits, ending in Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_offset(base: datetime, **delta) -> str:
    return iso_utc(base + timedelta(**delta))


def utc(year: int, month: int, day: int,
        hour: int = 0, minute: int = 0, second: int = 0, ms: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, ms * 1000, tzinfo=timezone.utc)


# A stable far-future anchor that all tests can rest on.
DEFAULT_BASE_CLOCK = utc(2026, 6, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# District (PRD §3.1)
# ---------------------------------------------------------------------------
def create_district_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": f"District-{_suffix()}",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def patch_district_payload(**overrides) -> Dict[str, Any]:
    """For PATCH /districts/{id} — accepts_inter_district_transfers,
    poverty_index_threshold, and optional version per PRD §4 / §2.6."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# School (PRD §3.1)
# ---------------------------------------------------------------------------
def create_school_payload(
    district_id: str,
    school_type: str = "NEIGHBORHOOD",
    grade_levels_offered: Optional[List[int]] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "district_id": district_id,
        "name": f"School-{_suffix()}",
        "school_type": school_type,
        "grade_levels_offered": list(grade_levels_offered) if grade_levels_offered else [5],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Program (PRD §3.1, §3.5)
# ---------------------------------------------------------------------------
def create_program_payload(
    school_id: str,
    grade_level: int = 5,
    academic_year: int = 2026,
    seats_total: int = 1,
    registration_open_at: Optional[str] = None,
    registration_close_at: Optional[str] = None,
    lottery_seed: Optional[str] = "seed-test",
    **overrides,
) -> Dict[str, Any]:
    if registration_open_at is None:
        registration_open_at = iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=1))
    if registration_close_at is None:
        registration_close_at = iso_utc(DEFAULT_BASE_CLOCK + timedelta(days=30))
    defaults: Dict[str, Any] = {
        "school_id": school_id,
        "grade_level": grade_level,
        "academic_year": academic_year,
        "seats_total": seats_total,
        "registration_open_at": registration_open_at,
        "registration_close_at": registration_close_at,
    }
    # PRD §3.1: lottery_seed is optional at creation, must be set before
    # draw — emit only when explicitly supplied (None means "omit").
    if lottery_seed is not None:
        defaults["lottery_seed"] = lottery_seed
    defaults.update(overrides)
    return defaults


def patch_program_payload(**overrides) -> Dict[str, Any]:
    """For PATCH /programs/{id} — any subset of seats_total,
    lottery_seed, registration_close_at, and optional version per PRD §4
    / §2.6."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Family (PRD §3.2)
# ---------------------------------------------------------------------------
def create_family_payload(
    residency_district_id: str,
    poverty_index_score: float = 0.10,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "residency_district_id": residency_district_id,
        "poverty_index_score": poverty_index_score,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Student (PRD §3.2)
# ---------------------------------------------------------------------------
def create_student_payload(
    family_id: str,
    grade_level_next_year: int = 5,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "family_id": family_id,
        "grade_level_next_year": grade_level_next_year,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Application (PRD §3.4)
# ---------------------------------------------------------------------------
def create_application_payload(
    student_id: str,
    program_id: str,
    choice_rank: int = 1,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "student_id": student_id,
        "program_id": program_id,
        "choice_rank": choice_rank,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Transfer requests (PRD §3.3)
# ---------------------------------------------------------------------------
def create_transfer_request_payload(
    application_id: str,
    target_district_id: str,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "application_id": application_id,
        "target_district_id": target_district_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.10)
# ---------------------------------------------------------------------------
def advance_clock_payload(target_now: str) -> Dict[str, Any]:
    return {"target_now": target_now}


__all__ = [
    "iso_utc",
    "iso_offset",
    "utc",
    "DEFAULT_BASE_CLOCK",
    "create_district_payload",
    "patch_district_payload",
    "create_school_payload",
    "create_program_payload",
    "patch_program_payload",
    "create_family_payload",
    "create_student_payload",
    "create_application_payload",
    "create_transfer_request_payload",
    "advance_clock_payload",
]
