"""In-memory data store and logical clock for the Airport Badging & SIDA API.

The store starts completely empty on every boot. Nothing is seeded here or
anywhere else; every entity is constructed through the declared API surface.
"""

from __future__ import annotations

import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Stores: one dict per entity kind, keyed by id. Insertion order preserved.
# ---------------------------------------------------------------------------

STORES = {
    "sponsors": {},
    "applicants": {},
    "applications": {},
    "training_completions": {},
    "badges": {},
    "escort_privileges": {},
    "access_events": {},
    "violations": {},
    "audit_cycles": {},
}

_seq_counter = itertools.count(1)

# Logical clock: exactly 2026-08-01T00:00:00Z at startup; never wall clock.
CLOCK = {
    "now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": "2026-08-01T00:00:00Z",
}


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    return next(_seq_counter)


def utcnow() -> datetime:
    """Real wall clock — used only for metadata timestamps (created_at etc.)."""
    return datetime.now(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def fmt_clock(dt: datetime) -> str:
    """Logical-clock timestamp serialization (no fraction when integral)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:06d}Z".format(dt.microsecond)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_now() -> datetime:
    return CLOCK["now"]


def set_clock(dt: datetime, raw: str) -> None:
    CLOCK["now"] = dt
    CLOCK["raw"] = raw


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value):
    """Parse an ISO 8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not _ISO_RE.match(v):
        return None
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date; returns date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar-month addition preserving day-of-month (clamped to month length)."""
    total = dt.year * 12 + (dt.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    if month == 12:
        first_next = datetime(year + 1, 1, 1)
    else:
        first_next = datetime(year, month + 1, 1)
    last_day = (first_next - timedelta(days=1)).day
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def stamp_new(rec: dict) -> dict:
    """Apply common system fields to a freshly created primary resource."""
    ts = fmt_ts(utcnow())
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_append_only(rec: dict) -> dict:
    """Append-only resources (TrainingCompletion, AccessEvent) carry id + created_at only."""
    rec["id"] = new_id()
    rec["created_at"] = fmt_ts(utcnow())
    rec["_seq"] = next_seq()
    return rec


def touch(rec: dict) -> None:
    """Refresh updated_at and bump version on a mutated primary resource."""
    rec["updated_at"] = fmt_ts(utcnow())
    rec["version"] = rec.get("version", 1) + 1


def public(rec: dict) -> dict:
    """Strip internal bookkeeping keys (underscore-prefixed) for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
