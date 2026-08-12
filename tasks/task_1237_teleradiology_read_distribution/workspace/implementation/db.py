"""In-memory data store for the teleradiology read-distribution API.

The store starts completely empty on every boot. No entity is seeded,
preloaded, or hardcoded at startup. All persistence is process-local
dictionaries keyed by id; the logical clock starts at exactly
2026-05-01T00:00:00Z and is advanced only via POST /telerad/_clock/set_current_utc.
"""

import threading
from datetime import datetime, timezone

CLOCK_START_ISO = "2026-05-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO-8601 instant (accepts trailing Z) into an aware datetime."""
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError("not an iso8601 string")


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.hospitals = {}
        self.radiologists = {}
        self.shifts = {}
        self.routing_policies = {}
        self.studies = {}
        self.assignments = {}
        self.reports = {}
        self.discrepancy_cases = {}
        self.critical_notices = {}
        self.credential_grants = {}
        self.billing_periods = {}
        self.invoices = {}
        # Logical clock; never the wall clock.
        self.clock = _parse_iso(CLOCK_START_ISO)

    def now(self):
        return self.clock

    def set_clock(self, to_iso8601):
        self.clock = _parse_iso(to_iso8601)
        return self.clock


# Module-level singleton, empty at import time.
store = Store()
