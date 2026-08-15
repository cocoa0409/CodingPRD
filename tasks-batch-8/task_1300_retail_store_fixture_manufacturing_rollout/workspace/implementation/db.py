"""In-memory data store for the Fixture Rollout API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

programs: dict[str, dict] = {}
prototypes: dict[str, dict] = {}
kits: dict[str, dict] = {}
waves: dict[str, dict] = {}
reservations: dict[str, dict] = {}
deliveries: dict[str, dict] = {}
claims: dict[str, dict] = {}
signoffs: dict[str, dict] = {}
ledgers: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_current_utc: str = _CLOCK_DEFAULT


def get_current_utc() -> str:
    return _current_utc


def set_current_utc(value: str) -> None:
    global _current_utc
    _current_utc = value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Current wall-clock timestamp for created_at/updated_at (ISO 8601 UTC,
    three fractional digits, trailing Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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
