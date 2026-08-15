"""In-memory data store for the Joint Trench Undergrounding API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface; nothing is seeded here.

Timestamps:
- created_at / updated_at are wall-clock ISO 8601 UTC with three fractional
  digits (PRD section 2.4).
- Domain timestamps ("clock timestamp" fields) come from the logical clock,
  which starts at exactly 2026-08-01T00:00:00Z and moves only via
  POST /api/_clock/set_current_utc (PRD section 2.5).
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

projects: dict[str, dict] = {}
participations: dict[str, dict] = {}
segments: dict[str, dict] = {}
slots: dict[str, dict] = {}
parcels: dict[str, dict] = {}
easements: dict[str, dict] = {}
permits: dict[str, dict] = {}
conversions: dict[str, dict] = {}
outages: dict[str, dict] = {}
change_orders: dict[str, dict] = {}
cost_entries: dict[str, dict] = {}
trueup_runs: dict[str, dict] = {}
invoices: dict[str, dict] = {}
restoration_tasks: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_clock_raw: str = _CLOCK_DEFAULT


def get_clock_raw() -> str:
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


def wall_now_iso() -> str:
    """Wall-clock timestamp for created_at/updated_at (ISO 8601 UTC,
    three fractional digits, trailing Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq() -> int:
    """Monotonic insertion sequence used as a stable list-ordering tiebreak."""
    return next(_seq_counter)


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = wall_now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = wall_now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity
