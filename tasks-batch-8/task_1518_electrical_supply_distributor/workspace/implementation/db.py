"""In-memory data store for the Electrical Supply Distributor API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time (PRD §2.5).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from flask import g


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

contractors: dict[str, dict] = {}
catalog_items: dict[str, dict] = {}
job_accounts: dict[str, dict] = {}
quotes: dict[str, dict] = {}
quote_lines: dict[str, dict] = {}
substitution_requests: dict[str, dict] = {}
releases: dict[str, dict] = {}
release_lines: dict[str, dict] = {}
backorder_allocations: dict[str, dict] = {}
rebate_programs: dict[str, dict] = {}
rebate_claims: dict[str, dict] = {}

# Commodity index readings: month ("YYYY-MM") -> Decimal value
index_readings: dict[str, object] = {}

# Global mutation lock (all writes are atomic per request) and a monotonic
# sequence used as a deterministic tiebreaker for created_at ordering.
lock = threading.RLock()
_seq = 0


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_dt() -> datetime:
    return _clock


def set_clock(dt: datetime) -> None:
    global _clock
    _clock = dt


def clock_date():
    return _clock.date()


def clock_month() -> str:
    return _clock.strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock timestamp for created_at/updated_at: ISO 8601 UTC with
    exactly three fractional digits and a trailing Z (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def new_record(fields: dict) -> dict:
    """Mint a resource with the PRD §2.4 common fields."""
    ts = now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec: dict) -> None:
    """Bump version once per request per record and refresh updated_at.

    PRD §2.4: version increments by 1 on every mutation, including derived
    field reconciliation performed as a side effect of an operation on a
    different resource. Multiple field changes to the same record within one
    request count as one mutation.
    """
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if rec["id"] in touched:
        return
    touched.add(rec["id"])
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def sort_key(rec: dict):
    """created_at ASC ordering; _seq breaks same-millisecond ties in
    insertion order (never by id)."""
    return (rec["created_at"], rec["_seq"])
