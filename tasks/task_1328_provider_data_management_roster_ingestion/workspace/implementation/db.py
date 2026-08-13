"""In-memory data store. The store starts empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class LogicalClock:
    """Server-maintained logical clock. Never falls back to wall-clock time.
    Startup default is exactly 2026-08-01T00:00:00Z."""

    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt

    def now_iso(self):
        return iso_ts(self._current)

    def today(self):
        """Logical clock date as an ISO date string (YYYY-MM-DD)."""
        return self._current.date().isoformat()


CLOCK = LogicalClock()


def iso_ts(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits, e.g.
    2025-05-24T10:30:00.123Z."""
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return s


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


# ---------------------------------------------------------------------------
# Stores — plain dicts keyed by id. All start empty.
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.roster_sources = {}
        self.roster_files = {}
        self.roster_rows = {}
        self.providers = {}
        self.provider_attributes = {}
        self.provider_aliases = {}
        self.attribute_conflicts = {}
        self.distribution_targets = {}
        self.distribution_batches = {}
        self.distribution_items = {}
        self.attestation_campaigns = {}
        self.attestation_requests = {}
        self.data_quality_scores = {}
        self.provider_merge_records = {}


DB = Store()
