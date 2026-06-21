"""In-memory data store and system-field helpers.

Storage is pure in-process Python dicts keyed by id. The test harness restarts
this process via start.sh before every test, so the store is wiped to empty on
every boot. NOTHING is seeded here — every entity is created by a test via the
declared API surface.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# In-memory tables. Each maps id -> record dict. Empty at boot, never seeded.
# ---------------------------------------------------------------------------
class Store:
    def __init__(self) -> None:
        self.guardians: dict = {}
        self.children: dict = {}
        self.emergency_contacts: dict = {}
        self.authorization_forms: dict = {}
        self.programs: dict = {}
        self.sessions: dict = {}
        self.weekly_offerings: dict = {}
        self.scholarship_awards: dict = {}
        self.enrollments: dict = {}
        self.invoices: dict = {}
        self.payments: dict = {}
        self.weather_events: dict = {}
        self.audit_entries: dict = {}
        # monotonic sequence to provide a stable secondary sort key for records
        # created within the same millisecond (created_at has ms precision only).
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# id / timestamp / request-id helpers
# ---------------------------------------------------------------------------
def new_id() -> str:
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """Server-generated request id beginning with 'req_' (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"
