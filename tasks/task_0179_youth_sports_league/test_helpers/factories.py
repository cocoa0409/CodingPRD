"""Payload factories — one per endpoint that accepts an input body.

Each factory emits the JSON body shape the PRD declares for the request
(PRD §3 narratives + §4 endpoint table). Tests pass overrides for the
values they want to control; everything else gets sensible defaults.
Only PRD-declared input fields are produced; computed / system fields
are intentionally omitted.

PRD §2.10: ISO 8601 UTC timestamps with three fractional digits.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.10 ISO 8601 UTC with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' suffixes."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_milliseconds(iso_ts: str, ms: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(milliseconds=ms))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_hours(iso_ts: str, hours: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(hours=hours))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def date_only_iso(year: int, month: int, day: int) -> str:
    """Render a calendar date as an ISO instant at midnight UTC."""
    return iso_utc(datetime(year, month, day, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Random suffixes for cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def unique_name(prefix: str) -> str:
    return f"{prefix}-{random_suffix(10)}"


def unique_email(local_prefix: str = "user") -> str:
    return f"{local_prefix}-{random_suffix(10)}@example.com"


def unique_field_id(prefix: str = "F") -> str:
    return f"{prefix}-{random_suffix(6)}"


def unique_operator_id(prefix: str = "op") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Season — POST /league/seasons (PRD §3.1)
# ---------------------------------------------------------------------------
def create_season_payload(
    *,
    name: Optional[str] = None,
    age_division: str = "MAJORS",
    min_birth_date: Optional[str] = None,
    max_birth_date: Optional[str] = None,
    regular_season_start: Optional[str] = None,
    regular_season_end: Optional[str] = None,
    playoff_cutoff_date: Optional[str] = None,
    rainout_window_days: Optional[int] = None,
    volunteer_hours_required_per_family: Optional[float] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_name("Season"),
        "age_division": age_division,
        "min_birth_date":
            min_birth_date or TEST_DEFAULTS["SEASON_MIN_BIRTH_DATE"],
        "max_birth_date":
            max_birth_date or TEST_DEFAULTS["SEASON_MAX_BIRTH_DATE"],
        "regular_season_start":
            regular_season_start or TEST_DEFAULTS["SEASON_REGULAR_START"],
        "regular_season_end":
            regular_season_end or TEST_DEFAULTS["SEASON_REGULAR_END"],
        "playoff_cutoff_date":
            playoff_cutoff_date or TEST_DEFAULTS["SEASON_PLAYOFF_CUTOFF"],
    }
    if rainout_window_days is not None:
        payload["rainout_window_days"] = rainout_window_days
    if volunteer_hours_required_per_family is not None:
        payload["volunteer_hours_required_per_family"] = (
            volunteer_hours_required_per_family
        )
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Guardian — POST /league/guardians (PRD §3.2)
# ---------------------------------------------------------------------------
def create_guardian_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_name("Guardian"),
        "email": email or unique_email("guardian"),
        "phone": phone or TEST_DEFAULTS["DEFAULT_PHONE"],
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Player — POST /league/players (PRD §3.2)
# ---------------------------------------------------------------------------
def create_player_payload(
    *,
    season_id: str,
    guardian_id: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    birth_date: Optional[str] = None,
    birth_certificate_uri: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "first_name": first_name or unique_name("First"),
        "last_name": last_name or unique_name("Last"),
        "birth_date":
            birth_date or TEST_DEFAULTS["PLAYER_DEFAULT_BIRTH_DATE"],
        "guardian_id": guardian_id,
    }
    if birth_certificate_uri is not None:
        payload["birth_certificate_uri"] = birth_certificate_uri
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def verify_age_payload(
    *,
    birth_certificate_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.2: "The verification accepts an optional
    `birth_certificate_uri` in the body, which is used when the player
    was registered without one"."""
    payload: Dict[str, Any] = {}
    if birth_certificate_uri is not None:
        payload["birth_certificate_uri"] = birth_certificate_uri
    return payload


def record_evaluation_payload(*, evaluation_score: float) -> Dict[str, Any]:
    return {"evaluation_score": evaluation_score}


# ---------------------------------------------------------------------------
# Coach — POST /league/coaches (PRD §3.3)
# ---------------------------------------------------------------------------
def create_coach_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    background_check_passed: Optional[bool] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_name("Coach"),
        "email": email or unique_email("coach"),
    }
    if background_check_passed is not None:
        payload["background_check_passed"] = background_check_passed
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Referee — POST /league/referees (PRD §2.8)
# ---------------------------------------------------------------------------
def create_referee_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    certification_level: str = "LEVEL_2",
    weekly_assignment_cap: Optional[int] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_name("Ref"),
        "email": email or unique_email("ref"),
        "certification_level": certification_level,
    }
    if weekly_assignment_cap is not None:
        payload["weekly_assignment_cap"] = weekly_assignment_cap
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Team — POST /league/teams (PRD §3.3)
# ---------------------------------------------------------------------------
def create_team_payload(
    *,
    season_id: str,
    head_coach_id: str,
    draft_position: int,
    name: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "name": name or unique_name("Team"),
        "head_coach_id": head_coach_id,
        "draft_position": draft_position,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def draft_pick_payload(*, player_id: str) -> Dict[str, Any]:
    return {"player_id": player_id}


# ---------------------------------------------------------------------------
# Game — POST /league/games (PRD §3.4)
# ---------------------------------------------------------------------------
def create_game_payload(
    *,
    season_id: str,
    home_team_id: str,
    away_team_id: str,
    field_id: str,
    scheduled_start: str,
    game_type: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "field_id": field_id,
        "scheduled_start": scheduled_start,
    }
    if game_type is not None:
        payload["game_type"] = game_type
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def assign_referee_payload(
    *,
    referee_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"referee_id": referee_id}
    if version is not None:
        payload["version"] = version
    return payload


def postpone_payload(
    *,
    reason: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    if version is not None:
        payload["version"] = version
    return payload


def reschedule_payload(
    *,
    scheduled_start: str,
    referee_id: Optional[str] = None,
    field_id: Optional[str] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"scheduled_start": scheduled_start}
    if referee_id is not None:
        payload["referee_id"] = referee_id
    if field_id is not None:
        payload["field_id"] = field_id
    if version is not None:
        payload["version"] = version
    return payload


def record_result_payload(
    *,
    home_score: int,
    away_score: int,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "home_score": home_score,
        "away_score": away_score,
    }
    if version is not None:
        payload["version"] = version
    return payload


def forfeit_payload(
    *,
    forfeiting_team_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"forfeiting_team_id": forfeiting_team_id}
    if version is not None:
        payload["version"] = version
    return payload


def cancel_game_payload(
    *,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# VolunteerShift — POST /league/volunteer-shifts (PRD §3.7)
# ---------------------------------------------------------------------------
def create_volunteer_shift_payload(
    *,
    season_id: str,
    guardian_id: str,
    role: str,
    scheduled_start: str,
    scheduled_end: str,
    game_id: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "guardian_id": guardian_id,
        "role": role,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if game_id is not None:
        payload["game_id"] = game_id
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — POST /_clock/advance (PRD §2.10)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str) -> Dict[str, Any]:
    return {"to": to}


__all__ = [
    # Time helpers
    "iso_utc",
    "utcnow",
    "parse_iso",
    "add_milliseconds",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    "date_only_iso",
    # Uniqueness helpers
    "random_suffix",
    "unique_name",
    "unique_email",
    "unique_field_id",
    "unique_operator_id",
    # Season
    "create_season_payload",
    # Guardian
    "create_guardian_payload",
    # Player
    "create_player_payload",
    "verify_age_payload",
    "record_evaluation_payload",
    # Coach
    "create_coach_payload",
    # Referee
    "create_referee_payload",
    # Team
    "create_team_payload",
    "draft_pick_payload",
    # Game
    "create_game_payload",
    "assign_referee_payload",
    "postpone_payload",
    "reschedule_payload",
    "record_result_payload",
    "forfeit_payload",
    "cancel_game_payload",
    # VolunteerShift
    "create_volunteer_shift_payload",
    # Clock
    "clock_advance_payload",
]
