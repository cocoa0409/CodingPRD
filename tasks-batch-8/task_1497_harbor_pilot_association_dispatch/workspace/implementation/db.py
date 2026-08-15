"""In-memory data store plus the server-held logical clock.

The store starts empty on every boot; no seeding. All temporal reasoning
(created_at/updated_at stamps, actual_start/actual_end, finalized_at, tariff
resolution, endorsement currency, rest expiry, rolling duty windows) uses the
logical clock, never wall-clock time (PRD section 2.4).
"""
import uuid
from datetime import datetime, timezone

DB = {
    "pilots": {},
    "endorsements": {},
    "rotation_entries": {},
    "vessel_orders": {},
    "pilot_boats": {},
    "assignments": {},
    "invoices": {},
    "incidents": {},
    "apprentices": {},
    "tariff_schedules": {},
    "distribution_runs": {},
}

# Startup default per PRD 2.4 / scaffold endpoint table.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse(value):
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_CLOCK = {"current": _parse(DEFAULT_CLOCK)}
_SEQ = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic creation sequence used as a deterministic tie-break when two
    rows share the same logical-clock created_at."""
    _SEQ["n"] += 1
    return _SEQ["n"]


def now():
    return _CLOCK["current"]


def set_clock(dt):
    _CLOCK["current"] = dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(now())


def touch(entity):
    """Common-field mutation bookkeeping (PRD 2.5): refresh updated_at from the
    logical clock and increment version by exactly one."""
    entity["updated_at"] = now()
    entity["version"] += 1
