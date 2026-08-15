"""In-memory data store. The store starts empty on every boot; no seeding.

The logical clock (PRD 2.8) starts at exactly 2026-08-01T00:00:00Z and is only
advanced via POST /accreditation/_clock/set_current_utc. It never falls back
to wall-clock time for temporal rules.
"""
import uuid
from datetime import datetime, timezone

DB = {
    "systems": {},
    "campuses": {},
    "standards": {},
    "terms": {},
    "ratings": {},
    "evidence": {},
    "instruments": {},
    "survey_windows": {},
    "survey_responses": {},
    "goals": {},
    "indicators": {},
    "visits": {},
    "reviewers": {},
    "assignments": {},
    "findings": {},
    "action_items": {},
    "interim_reports": {},
    "fee_schedules": {},
    "invoices": {},
    "payments": {},
}

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(text):
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# Logical clock state; stored as an aware datetime.
_CLOCK = {"now": _parse_iso(DEFAULT_CLOCK_ISO)}


def new_id():
    return str(uuid.uuid4())


def wall_now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits.

    Used for api_request_timestamp / created_at / updated_at metadata (these
    are audit stamps, not part of temporal business rules).
    """
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    """Return the current logical-clock instant (aware datetime)."""
    return _CLOCK["now"]


def clock_now_iso():
    return fmt_iso(_CLOCK["now"])


def clock_set(dt):
    _CLOCK["now"] = dt
