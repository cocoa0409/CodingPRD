"""In-memory data store and logical clock for the Hospital Price Transparency API.

The store starts completely empty on every boot. Tests build all state via the
declared API surface. The logical clock starts at exactly 2026-08-01T00:00:00Z
and never falls back to wall-clock time (PRD section 2.5).
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity stores (keyed by id). Start empty — no seeding.
# ---------------------------------------------------------------------------

facilities: dict[str, dict] = {}
payers: dict[str, dict] = {}
payer_contracts: dict[str, dict] = {}
service_items: dict[str, dict] = {}
standard_charge_records: dict[str, dict] = {}
payer_negotiated_rates: dict[str, dict] = {}
shoppable_service_lists: dict[str, dict] = {}
publication_cycles: dict[str, dict] = {}
machine_readable_files: dict[str, dict] = {}
discrepancy_reports: dict[str, dict] = {}

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
# Identity / timestamp helpers
# ---------------------------------------------------------------------------

_SEQ = itertools.count(1)


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    return next(_SEQ)


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC, three fractional digits, trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    """Entity timestamp source: the logical clock (PRD 2.5)."""
    return format_iso(_CLOCK["now"])


def parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (or bare date) to an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def bump(entity: dict) -> None:
    """Every mutation — direct or cascade-delivered — refreshes updated_at
    and increments version by exactly one (PRD 2.4)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()


def public(entity: dict) -> dict:
    """Strip internal bookkeeping keys (underscore-prefixed)."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
