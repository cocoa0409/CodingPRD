"""In-memory data store and logical clock for the ACH ODFI Origination API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id). Start empty.
# ---------------------------------------------------------------------------

originators: dict[str, dict] = {}
cutoff_windows: dict[str, dict] = {}
ach_files: dict[str, dict] = {}
ach_entries: dict[str, dict] = {}
return_cases: dict[str, dict] = {}
noc_records: dict[str, dict] = {}
reversal_requests: dict[str, dict] = {}
return_rate_snapshots: dict[str, dict] = {}
risk_cases: dict[str, dict] = {}
settlement_batches: dict[str, dict] = {}
gl_postings: dict[str, dict] = {}

# Non-serialized bookkeeping: entry ids transmitted at each batch's dispatch.
dispatch_sets: dict[str, list[str]] = {}


# ---------------------------------------------------------------------------
# Logical clock (test-driving). Never wall-clock.
# ---------------------------------------------------------------------------


def _default_clock_dt() -> datetime:
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


_CLOCK = {"now": _default_clock_dt()}


def clock() -> datetime:
    return _CLOCK["now"]


def set_clock(dt: datetime) -> None:
    _CLOCK["now"] = dt


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC, three fractional digits, trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso() -> str:
    return format_iso(_CLOCK["now"])


def now_logical_iso() -> str:
    """created_at/updated_at/posted_at source: the logical clock."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def stamp_new(entity: dict) -> dict:
    """Common system fields per PRD §2.5: id/created_at/updated_at/version."""
    ts = now_logical_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_new_light(entity: dict) -> dict:
    """For ReturnRateSnapshot / GlPosting: only id + created_at (§2.5)."""
    entity["id"] = new_id()
    entity["created_at"] = now_logical_iso()
    return entity


def touch(entity: dict) -> None:
    """Refresh updated_at (logical clock) and bump version on mutation."""
    entity["updated_at"] = now_logical_iso()
    entity["version"] = entity.get("version", 1) + 1
