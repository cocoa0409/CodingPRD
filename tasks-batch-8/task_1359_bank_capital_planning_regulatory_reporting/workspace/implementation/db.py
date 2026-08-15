"""In-memory data store for the Bank Capital Planning API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. Nothing is seeded or persisted.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

banks: dict[str, dict] = {}
reporting_periods: dict[str, dict] = {}
capital_instruments: dict[str, dict] = {}
risk_exposures: dict[str, dict] = {}
capital_plans: dict[str, dict] = {}
stress_scenarios: dict[str, dict] = {}
call_reports: dict[str, dict] = {}
edit_exceptions: dict[str, dict] = {}
distribution_requests: dict[str, dict] = {}
sub_debt_issuances: dict[str, dict] = {}
pca_threshold_events: dict[str, dict] = {}
icaap_documents: dict[str, dict] = {}

# Monotonic insertion counter used as a deterministic list-sort tiebreak.
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)


# ---------------------------------------------------------------------------
# Logical clock (never wall-clock for business logic)
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_current_utc: str = _CLOCK_DEFAULT


def get_current_utc() -> str:
    return _current_utc


def set_current_utc(value: str) -> None:
    global _current_utc
    _current_utc = value


def get_current_utc_dt() -> "datetime":
    """Current logical clock as a datetime (UTC)."""
    v = _current_utc
    if isinstance(v, str) and v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock timestamp for created_at/updated_at (ISO 8601 UTC, three
    fractional digits, trailing Z) per PRD 2.4."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def touch(entity: dict, bump: bool = True) -> None:
    """Refresh updated_at and (optionally) bump version on a mutated entity."""
    entity["updated_at"] = now_iso()
    if bump:
        entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def public(entity: dict) -> dict:
    """Serialize an entity, dropping internal keys (underscore-prefixed)."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
