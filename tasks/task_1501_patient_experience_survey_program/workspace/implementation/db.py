"""In-memory data store for the Patient Experience Survey API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface; nothing is seeded here.

All entity timestamps (created_at, updated_at, received_at, superseded_at,
published_at, achieved_at, acknowledged_at) come from the server-maintained
logical clock (PRD section 2.4), which starts at exactly
2026-08-01T00:00:00Z and moves only via POST /_clock/set_current_utc. The
verbatim clock string is stamped onto entities.
"""

from __future__ import annotations

import itertools
import uuid


# ---------------------------------------------------------------------------
# Entity stores (keyed by id) — empty at boot
# ---------------------------------------------------------------------------

programs: dict[str, dict] = {}
vendors: dict[str, dict] = {}
cycles: dict[str, dict] = {}
units: dict[str, dict] = {}
providers: dict[str, dict] = {}
discharges: dict[str, dict] = {}
sample_cases: dict[str, dict] = {}
responses: dict[str, dict] = {}
initiatives: dict[str, dict] = {}
tickets: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_clock_raw: str = _CLOCK_DEFAULT


def clock_now() -> str:
    """Current logical clock reading (verbatim ISO 8601 UTC string)."""
    return _clock_raw


def set_clock_raw(value: str) -> None:
    global _clock_raw
    _clock_raw = value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_seq_counter = itertools.count(1)


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    """Monotonic insertion sequence; stable tiebreak for created_at ordering."""
    return next(_seq_counter)


def stamp_new(entity: dict) -> dict:
    ts = clock_now()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity: dict) -> None:
    """Refresh updated_at (logical clock) and bump version on a mutation."""
    entity["updated_at"] = clock_now()
    entity["version"] = entity.get("version", 1) + 1
