"""In-memory data store, the logical mill clock, and id/timestamp helpers.

Storage is process-local memory only: no files, no database, and no seeding.
The store starts empty on every boot; every entity is created through the
declared API surface.
"""
import uuid
from datetime import datetime, timezone
from itertools import count

STORE = {
    "customers": {},
    "employees": {},
    "ingredients": {},
    "price_ticks": {},
    "contracts": {},
    "bins": {},
    "formulas": {},
    "orders": {},
    "lines": {},
    "batches": {},
    "weighments": {},
    "flushes": {},
    "samples": {},
    "trucks": {},
    "trips": {},
}

_seq = count(1)

# The logical mill clock. Before any adjustment it reads exactly
# 2026-05-01T00:00:00Z (PRD section 2.5) and never follows the wall clock.
_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def clock_now():
    return _CLOCK


def set_clock(dt):
    global _CLOCK
    _CLOCK = dt


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(_CLOCK)


def make_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "_created_dt": _CLOCK,
    }


def bump(rec):
    """PRD 2.4: version increments by exactly one with every mutation."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()
