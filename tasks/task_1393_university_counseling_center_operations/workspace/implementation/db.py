"""In-memory data store and logical clock for the University Counseling Center API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id). Start empty.
# ---------------------------------------------------------------------------

students: dict[str, dict] = {}
counselors: dict[str, dict] = {}
intake_assessments: dict[str, dict] = {}
episodes: dict[str, dict] = {}
sessions: dict[str, dict] = {}
group_programs: dict[str, dict] = {}
group_enrollments: dict[str, dict] = {}
crisis_shifts: dict[str, dict] = {}
crisis_visits: dict[str, dict] = {}
referrals: dict[str, dict] = {}
outcome_measures: dict[str, dict] = {}
policies: dict[str, dict] = {}
clinical_notes: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock (test-driving). Never wall-clock.
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def _default_clock_dt() -> datetime:
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


_CLOCK = {"now": _default_clock_dt()}


def clock() -> datetime:
    return _CLOCK["now"]


def set_clock(dt: datetime) -> None:
    _CLOCK["now"] = dt


def clock_iso() -> str:
    """Logical clock rendered as ISO 8601 UTC with three fractional digits."""
    return format_iso(_CLOCK["now"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC, three fractional digits, trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_logical_iso() -> str:
    """Timestamp used for created_at/updated_at: derived from logical clock.

    The PRD requires created_at/updated_at to be system-managed timestamps. We
    source them from the logical clock so time-driven cascades (referral lapse,
    engagement window) compare apples to apples.
    """
    return format_iso(_CLOCK["now"])


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity: dict) -> None:
    """Refresh updated_at (logical clock) and bump version on mutation."""
    entity["updated_at"] = now_logical_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = now_logical_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_new_light(entity: dict) -> dict:
    """For IntakeAssessment / GroupEnrollment / OutcomeMeasure / ClinicalNote:
    only id + created_at; no updated_at, no version."""
    entity["id"] = new_id()
    entity["created_at"] = now_logical_iso()
    return entity
