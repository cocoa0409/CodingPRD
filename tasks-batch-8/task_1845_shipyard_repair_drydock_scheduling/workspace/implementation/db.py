"""In-memory data store for the Shipyard Repair & Drydock API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. A server-side logical clock (never the wall clock)
drives every time-dependent rule; it starts at exactly 2026-08-01T00:00:00Z.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

docks: dict[str, dict] = {}
vessels: dict[str, dict] = {}
subcontractors: dict[str, dict] = {}
projects: dict[str, dict] = {}
reservations: dict[str, dict] = {}
work_items: dict[str, dict] = {}
change_orders: dict[str, dict] = {}
surveys: dict[str, dict] = {}
permits: dict[str, dict] = {}
warranty_claims: dict[str, dict] = {}

# Monotonic creation sequence (tiebreak for created_at ordering).
_seq_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_current_utc: str = _CLOCK_DEFAULT


def get_current_utc() -> str:
    """The raw logical-clock string exactly as last supplied."""
    return _current_utc


def set_current_utc(value: str) -> None:
    global _current_utc
    _current_utc = value


def clock_dt() -> datetime:
    """The current logical time as an aware UTC datetime."""
    from util import parse_iso8601  # local import to avoid a cycle

    return parse_iso8601(_current_utc, "current_utc")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Logical-clock timestamp for created_at/updated_at (ISO 8601 UTC, three
    fractional digits, trailing Z). PRD 2.5: all time-dependent behaviour is
    evaluated against the server-side logical clock, never the wall clock."""
    dt = clock_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version by exactly one on a mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next(_seq_counter)
    return entity
