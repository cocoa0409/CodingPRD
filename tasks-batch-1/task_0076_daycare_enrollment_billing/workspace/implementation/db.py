"""In-memory data store, clock, and id/timestamp helpers.

Storage is in-memory only. The test harness restarts this process before
every test, so the store is fresh on every boot. Nothing is seeded here.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Test-driving clock (PRD §2.10)
# ---------------------------------------------------------------------------
class Clock:
    """Server notion of 'now'. Pinnable via POST /_clock/set_current_utc."""

    def __init__(self):
        self._pinned = None  # datetime (tz-aware UTC) or None

    def set(self, dt: datetime) -> None:
        self._pinned = dt.astimezone(timezone.utc)

    def now(self) -> datetime:
        if self._pinned is not None:
            return self._pinned
        return datetime.now(timezone.utc)


clock = Clock()


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.centers = {}
        self.classrooms = {}
        self.families = {}
        self.sliding_scale = {}
        self.children = {}
        self.waitlist_entries = {}
        self.enrollments = {}
        self.attendance_records = {}
        self.invoices = {}
        self.payments = {}
        self.tax_statements = {}
        self._seq = 0  # monotonic creation sequence for stable created_at tie-breaks

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    return iso(clock.now())


def iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
