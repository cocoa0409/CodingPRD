"""In-memory data store and logical clock.

Storage is process-local Python dicts keyed by id. There is NO seeding: every
collection starts empty on every boot. Each per-test reboot via start.sh wipes
all state because nothing here is persisted to disk.
"""

import uuid
import threading
from datetime import datetime, timezone


class Clock:
    """Server logical UTC clock.

    Defaults to real wall-clock time but can be pinned via POST /_clock/set so
    tests can drive interest accrual and date-stamped postings deterministically.
    """

    def __init__(self):
        self._fixed = None  # datetime (tz-aware UTC) or None for wall clock

    def now(self):
        if self._fixed is not None:
            return self._fixed
        return datetime.now(timezone.utc)

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._fixed = dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        self._req_seq = 0
        # Each entity collection is an ordered dict keyed by id.
        self.custodial_parties = {}
        self.noncustodial_parties = {}
        self.employers = {}
        self.support_orders = {}
        self.income_withholding_orders = {}
        self.remittances = {}
        self.allocations = {}
        self.ledger_entries = {}
        self.disbursements = {}
        self.modifications = {}
        self.enforcement_actions = {}

    # -- id / timestamp helpers ------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def now_iso(self):
        """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
        return iso_millis(self.clock.now())

    def new_request_id(self):
        self._req_seq += 1
        return "req_" + uuid.uuid4().hex[:20]


def iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with milliseconds and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Single process-wide store instance. Created empty at import; never seeded.
store = Store()
