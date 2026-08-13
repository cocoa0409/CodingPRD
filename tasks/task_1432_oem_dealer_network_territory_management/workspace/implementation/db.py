"""In-memory data store for the OEM Dealer Network API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface — nothing is seeded here.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

dealers: dict[str, dict] = {}
agreements: dict[str, dict] = {}
assignments: dict[str, dict] = {}
targets: dict[str, dict] = {}
unit_sales: dict[str, dict] = {}
advances: dict[str, dict] = {}
claims: dict[str, dict] = {}
parts_returns: dict[str, dict] = {}
certifications: dict[str, dict] = {}
leads: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.6)
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_current_utc: str = _CLOCK_DEFAULT


def get_current_utc() -> str:
    return _current_utc


def set_current_utc(value: str) -> None:
    global _current_utc
    _current_utc = value


def clock_datetime() -> datetime:
    """Current logical clock as an aware UTC datetime."""
    text = _current_utc.strip()
    if text.endswith("Z"):
        dt = datetime.fromisoformat(text[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_date():
    """Current logical date (date part of the logical clock)."""
    return clock_datetime().date()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_seq = itertools.count(1)


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
    # Internal monotonic creation-order marker (never serialized). Wall-clock
    # timestamps only have millisecond precision, so creation ordering and the
    # created_at tie-breaks in the spec are implemented via this sequence.
    entity["_seq"] = next(_seq)
    return entity
