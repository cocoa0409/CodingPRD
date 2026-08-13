"""In-memory data store for the Household Employer Payroll API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. Nothing is seeded here.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

employers: dict[str, dict] = {}
state_rule_packs: dict[str, dict] = {}
registrations: dict[str, dict] = {}
workers: dict[str, dict] = {}
agreements: dict[str, dict] = {}
timesheets: dict[str, dict] = {}
pay_runs: dict[str, dict] = {}
paychecks: dict[str, dict] = {}
leave_requests: dict[str, dict] = {}
tax_accounts: dict[str, dict] = {}
deposits: dict[str, dict] = {}
filings: dict[str, dict] = {}
policies: dict[str, dict] = {}
year_end_packages: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock — default is exactly 2026-08-01T00:00:00Z, never wall clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_current_utc: str = _CLOCK_DEFAULT


def get_current_utc() -> str:
    return _current_utc


def set_current_utc(value: str) -> None:
    global _current_utc
    _current_utc = value


def clock_now_dt() -> datetime:
    """Logical clock instant as an aware UTC datetime."""
    return parse_iso_dt(_current_utc)


def clock_today() -> str:
    """Logical clock current calendar date (YYYY-MM-DD, UTC)."""
    return clock_now_dt().strftime("%Y-%m-%d")


def clock_year() -> int:
    return clock_now_dt().year


def parse_iso_dt(value: str) -> datetime:
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


# Monotonic insertion sequence: the logical clock produces identical
# created_at timestamps for entities created in one request, so list ordering
# (created_at ASC) falls back to insertion order as the deterministic tiebreak.
_seq = itertools.count(1)


def now_iso() -> str:
    """Logical-clock timestamp for created_at/updated_at/submitted_at style
    fields (ISO 8601 UTC, three fractional digits, trailing Z)."""
    dt = clock_now_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version by exactly 1 on a mutated entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next(_seq)
    return entity


def stamp_new_immutable(entity: dict) -> dict:
    """For StateRulePack and TaxDeposit: id + created_at only."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    entity["_seq"] = next(_seq)
    return entity
