"""In-memory data store for the Restaurant Equipment Dealer API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface; nothing is seeded here.

Timestamps (created_at / updated_at / submitted_at / opened_at) come from the
server's logical clock (PRD section 2.9): it starts at 2026-08-01T00:00:00Z and
is advanced only via POST /_clock/set_current_utc. It never falls back to
wall-clock time.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

customers: dict[str, dict] = {}
projects: dict[str, dict] = {}
layouts: dict[str, dict] = {}
items: dict[str, dict] = {}
fab_orders: dict[str, dict] = {}
quotes: dict[str, dict] = {}
filings: dict[str, dict] = {}
jobs: dict[str, dict] = {}
sessions: dict[str, dict] = {}
agencies: dict[str, dict] = {}
assignments: dict[str, dict] = {}
punch_items: dict[str, dict] = {}

# Global request/mutation lock: serializes handlers so OCC and capacity
# checks behave atomically under concurrent race tests.
LOCK = threading.RLock()

# Monotonic insertion counter used as a stable tie-breaker when logical
# created_at timestamps tie (the clock is frozen between advances).
_seq = itertools.count(1)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_dt: datetime = _CLOCK_DEFAULT


def now_dt() -> datetime:
    return _clock_dt


def set_current_utc(dt: datetime) -> None:
    global _clock_dt
    _clock_dt = dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return fmt_ts(_clock_dt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next(_seq)
    return entity


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version by exactly 1 on a mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1
