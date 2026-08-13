"""In-memory data store for the Utility Easement Encroachment API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. All domain timestamps derive from the logical clock
(PRD section 2.10), never from wall-clock time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

cases: dict[str, dict] = {}
documents: dict[str, dict] = {}
encroachments: dict[str, dict] = {}
offers: dict[str, dict] = {}
permits: dict[str, dict] = {}
zones: dict[str, dict] = {}
violations: dict[str, dict] = {}
title_tasks: dict[str, dict] = {}
referrals: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock (default startup: exactly 2026-08-01T00:00:00Z)
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
_clock_dt: datetime = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_raw: str = _CLOCK_DEFAULT_RAW


def get_clock_dt() -> datetime:
    return _clock_dt


def get_current_utc() -> str:
    return _clock_raw


def set_current_utc(raw: str, dt: datetime) -> None:
    global _clock_dt, _clock_raw
    _clock_dt = dt
    _clock_raw = raw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_seq: int = 0


def next_seq() -> int:
    """Monotonic creation sequence — final tie-break for created_at orderings
    (never the id, per the PRD)."""
    global _seq
    _seq += 1
    return _seq


def new_id() -> str:
    return str(uuid.uuid4())


def fmt_dt(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    """Current logical-clock timestamp for created_at/updated_at."""
    return fmt_dt(_clock_dt)


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1
