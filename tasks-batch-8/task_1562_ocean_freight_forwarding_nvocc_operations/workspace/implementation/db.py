"""In-memory data store and logical clock for the Ocean Freight NVOCC API.

The store starts completely empty on every boot. Tests build all state via the
declared API surface. The logical clock starts at exactly 2026-08-01T00:00:00Z
and never falls back to wall-clock time (PRD section 2.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id). Start empty.
# ---------------------------------------------------------------------------

shippers: dict[str, dict] = {}
tariffs: dict[str, dict] = {}
carrier_contracts: dict[str, dict] = {}
surety_bonds: dict[str, dict] = {}
voyages: dict[str, dict] = {}
bookings: dict[str, dict] = {}
consolidations: dict[str, dict] = {}
container_assignments: dict[str, dict] = {}
bills_of_lading: dict[str, dict] = {}
compliance_filings: dict[str, dict] = {}
invoices: dict[str, dict] = {}
insurance_policies: dict[str, dict] = {}
cargo_claims: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Server-minted reference number sequences (BK-<seq>, CON-<seq>, ...)
# ---------------------------------------------------------------------------

_sequences: dict[str, int] = {}


def next_seq(kind: str) -> int:
    n = _sequences.get(kind, 0) + 1
    _sequences[kind] = n
    return n


# ---------------------------------------------------------------------------
# Insertion sequence (stable tie-break for created_at sorting)
# ---------------------------------------------------------------------------

_insertion_counter = {"n": 0}


def next_insertion() -> int:
    _insertion_counter["n"] += 1
    return _insertion_counter["n"]


# ---------------------------------------------------------------------------
# Logical clock (test-driving). Never wall-clock.
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def _default_clock_dt() -> datetime:
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


_CLOCK = {"now": _default_clock_dt()}


def clock() -> datetime:
    return _CLOCK["now"]


def set_clock(dt: datetime) -> None:
    _CLOCK["now"] = dt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def format_iso3(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits (created_at/updated_at)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC for domain datetime fields.

    Drops the fractional part when it is exactly zero so computed timestamps
    render like their inputs (e.g. "2026-08-31T00:00:00Z"); keeps three
    fractional digits otherwise.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    """created_at / updated_at source: logical clock, three fractional digits."""
    return format_iso3(_CLOCK["now"])


def now_domain_iso() -> str:
    """Logical clock rendered for domain datetime fields (stuffed_at, ...)."""
    return format_iso(_CLOCK["now"])


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity: dict) -> None:
    """Refresh updated_at (logical clock) and bump version on mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def write_if_changed(entity: dict, field: str, value) -> None:
    """Derived-field recompute: only a real write counts as a mutation."""
    if entity.get(field) != value:
        entity[field] = value
        touch(entity)


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_insertion()
    return entity
