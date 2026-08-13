"""In-memory data store for the Production Services API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. No seeding of any entity happens at startup.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

venues: dict[str, dict] = {}
technicians: dict[str, dict] = {}
productions: dict[str, dict] = {}
plots: dict[str, dict] = {}
rigging_points: dict[str, dict] = {}
assets: dict[str, dict] = {}
pull_list_entries: dict[str, dict] = {}
crew_calls: dict[str, dict] = {}
crew_assignments: dict[str, dict] = {}
power_plans: dict[str, dict] = {}
trucks: dict[str, dict] = {}
load_schedules: dict[str, dict] = {}
inspections: dict[str, dict] = {}
damage_reports: dict[str, dict] = {}
settlements: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# Startup default is exactly 2026-08-01T00:00:00Z and never falls back to
# wall-clock time. Business rules (deadlines, gates, billing timestamps,
# depreciation ages) are evaluated against this clock only.

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_current_utc: str = _CLOCK_DEFAULT


def get_current_utc() -> str:
    return _current_utc


def set_current_utc(value: str) -> None:
    global _current_utc
    _current_utc = value


def clock_dt() -> datetime:
    """Logical clock as an aware UTC datetime."""
    text = _current_utc.strip()
    if text.endswith("Z"):
        dt = datetime.fromisoformat(text[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


_last_ts: str = ""


def now_iso() -> str:
    """Timestamp for created_at/updated_at (ISO 8601 UTC, three fractional
    digits, trailing Z). Monotonic: each call yields a value strictly greater
    than the previous one so created_at ASC ordering matches insertion order
    and never ties at 3-fractional-digit precision."""
    global _last_ts
    dt = datetime.now(timezone.utc)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    if ts <= _last_ts:
        # Nudge one millisecond past the previous timestamp.
        prev = datetime.fromisoformat(_last_ts[:-1] + "+00:00")
        from datetime import timedelta

        dt = prev + timedelta(milliseconds=1)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    _last_ts = ts
    return ts


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity
