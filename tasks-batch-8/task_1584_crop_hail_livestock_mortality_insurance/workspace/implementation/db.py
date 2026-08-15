"""In-memory data store for the Crop Hail & Livestock Mortality Insurance API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface; nothing is seeded here.

Each carrier runs its own logical clock (PRD 2.5), exposed as
Carrier.current_utc, starting at exactly 2026-08-01T00:00:00Z and moving only
via POST /carriers/{carrierId}/_clock/set_current_utc. All system timestamps
(created_at, updated_at, submitted_at, reported_at, inspected_at, decided_at,
issued_at, posted_at, established_at) are stamped verbatim from the owning
carrier's logical clock.
"""

from __future__ import annotations

import itertools
import uuid


# ---------------------------------------------------------------------------
# Entity stores (keyed by id) — empty at boot
# ---------------------------------------------------------------------------

carriers: dict[str, dict] = {}
growers: dict[str, dict] = {}
adjusters: dict[str, dict] = {}
rate_tables: dict[str, dict] = {}
federal_policies: dict[str, dict] = {}
policies: dict[str, dict] = {}
coverage_units: dict[str, dict] = {}
acreage_reports: dict[str, dict] = {}
head_reports: dict[str, dict] = {}
claims: dict[str, dict] = {}
field_inspections: dict[str, dict] = {}
vet_reports: dict[str, dict] = {}
determinations: dict[str, dict] = {}
indemnity_payments: dict[str, dict] = {}
dual_links: dict[str, dict] = {}
renewals: dict[str, dict] = {}
premium_payments: dict[str, dict] = {}


CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_seq_counter = itertools.count(1)


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    """Monotonic insertion sequence; stable tiebreak for created_at ordering."""
    return next(_seq_counter)


def stamp_new(entity: dict, ts: str) -> dict:
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity: dict, ts: str) -> None:
    """Refresh updated_at (logical clock) and bump version on a mutation."""
    entity["updated_at"] = ts
    entity["version"] = entity.get("version", 1) + 1
