"""In-memory data store, logical clock, and timestamp helpers for the VBC API.

The store starts completely empty on every boot — no seeding. Tests build all
state through the declared API surface. The logical clock starts at exactly
2026-08-01T00:00:00Z and is only advanced via POST /vbc/_clock/set_current_utc;
no code path falls back to wall-clock time for business date decisions.

created_at/updated_at are system-managed wall-clock timestamps (ISO 8601 UTC,
three fractional digits) issued through a strictly monotonic generator so that
creation order is always recoverable from created_at alone (the distribution
waterfall breaks fractional-part ties by Practice.created_at, never by id).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id). All start empty.
# ---------------------------------------------------------------------------

programs: dict[str, dict] = {}
practice_groups: dict[str, dict] = {}
practices: dict[str, dict] = {}
members: dict[str, dict] = {}
eligibility_spans: dict[str, dict] = {}
contracts: dict[str, dict] = {}
performance_years: dict[str, dict] = {}
attribution_runs: dict[str, dict] = {}
attribution_records: dict[str, dict] = {}
risk_scores: dict[str, dict] = {}
claims: dict[str, dict] = {}
quality_results: dict[str, dict] = {}
interim_reports: dict[str, dict] = {}
settlements: dict[str, dict] = {}
settlement_disputes: dict[str, dict] = {}
distribution_remittances: dict[str, dict] = {}
renewal_analyses: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4). Default exactly 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now() -> datetime:
    return _CLOCK["now"]


def set_clock(dt: datetime) -> None:
    _CLOCK["now"] = dt


def clock_date() -> date:
    """The logical clock's calendar date; source for all business date stamps."""
    return _CLOCK["now"].date()


def clock_date_iso() -> str:
    return clock_date().isoformat()


# ---------------------------------------------------------------------------
# Ids and timestamps
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_LAST_TS: dict[str, datetime] = {"last": datetime(1970, 1, 1, tzinfo=timezone.utc)}


def now_ts() -> str:
    """Strictly monotonic wall-clock timestamp for created_at/updated_at."""
    now = datetime.now(timezone.utc)
    last = _LAST_TS["last"]
    if now <= last:
        now = last + timedelta(milliseconds=1)
    _LAST_TS["last"] = now
    return format_ts(now)


def stamp_new(entity: dict) -> dict:
    ts = now_ts()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity: dict) -> None:
    """Unconditional mutation stamp: refresh updated_at, version += 1 (PRD §2.5)."""
    entity["updated_at"] = now_ts()
    entity["version"] = entity.get("version", 1) + 1


def apply_updates(entity: dict, updates: dict) -> None:
    """Conditional mutation stamp for cascade-driven recomputes: bumps
    updated_at/version only when at least one field value actually changes
    (PRD §2.5: a mutation is any change to any field)."""
    changed = False
    for key, value in updates.items():
        if entity.get(key) != value:
            entity[key] = value
            changed = True
    if changed:
        touch(entity)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(value: str) -> date:
    """Parse a strict YYYY-MM-DD date. Caller validates format beforehand."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)
