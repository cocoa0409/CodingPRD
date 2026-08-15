"""In-memory data store and the logical clock.

Storage is process-local dicts only: no SQLite, no files, no seeding.
The store starts empty on every boot; the logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time (PRD section 2.4).
"""

import threading
import uuid
from datetime import date, datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO-8601 string to an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO calendar date string (YYYY-MM-DD). Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return date.fromisoformat(value.strip())


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.clock = parse_dt(DEFAULT_CLOCK_ISO)
        self.seq = 0  # monotonic creation counter, stabilises created_at ordering
        self.lock = threading.RLock()
        self.customers = {}
        self.contracts = {}
        self.containers = {}
        self.trucks = {}
        self.manifests = {}
        self.visits = {}
        self.samples = {}
        self.quotes = {}
        self.settlements = {}
        self.lines = {}
        self.complaints = {}
        self.thefts = {}
        self.batches = {}

    def now_iso(self):
        return fmt_dt(self.clock)

    def clock_date(self):
        return self.clock.date()

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def stamp(self, rec):
        """Set creation common fields on a fresh record (PRD 2.5)."""
        rec["_seq"] = self.next_seq()
        rec["created_at"] = self.now_iso()
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1

    def bump(self, rec):
        """Mutation: version += 1 and updated_at refresh (PRD 2.5)."""
        rec["version"] += 1
        rec["updated_at"] = self.now_iso()


store = Store()
