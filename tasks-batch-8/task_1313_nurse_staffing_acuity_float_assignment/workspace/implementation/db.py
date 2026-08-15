"""In-memory data store for the Nurse Staffing API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface; nothing is seeded here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

units: dict[str, dict] = {}
nurses: dict[str, dict] = {}
matrix_rules: dict[str, dict] = {}
snapshots: dict[str, dict] = {}
shifts: dict[str, dict] = {}
assignments: dict[str, dict] = {}
float_requests: dict[str, dict] = {}
offers: dict[str, dict] = {}
sitter_requests: dict[str, dict] = {}
reports: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


_last_ms: int = 0


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits and trailing Z.

    Strictly monotonic at millisecond resolution so that created_at ordering
    (and created_at tie-breaks) are total and deterministic.
    """
    global _last_ms
    now = datetime.now(timezone.utc)
    ms = int(now.timestamp() * 1000)
    if ms <= _last_ms:
        ms = _last_ms + 1
    _last_ms = ms
    dt = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a mutated entity (PRD 2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity
