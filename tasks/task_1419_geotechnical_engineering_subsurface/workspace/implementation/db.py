"""In-memory data store and the logical clock.

Storage is process-local dicts only: no SQLite, no files, no seeding.
The store starts empty on every boot; the logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time (PRD section 2.6).
"""

import threading
import uuid
from datetime import datetime, timezone

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


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.clock = parse_dt(DEFAULT_CLOCK_ISO)
        self.seq = 0  # monotonic creation counter, stabilises created_at ordering
        self.lock = threading.RLock()
        self.clients = {}
        self.projects = {}
        self.plans = {}
        self.subcontractors = {}
        self.rig_assignments = {}
        self.clearances = {}
        self.borings = {}
        self.samples = {}
        self.orders = {}
        self.results = {}
        self.analyses = {}
        self.reports = {}
        self.visits = {}
        self.claims = {}
        self.auths = {}

    def now_iso(self):
        return fmt_dt(self.clock)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def stamp(self, rec):
        """Set creation common fields on a fresh record."""
        rec["_seq"] = self.next_seq()
        rec["created_at"] = self.now_iso()
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1

    def touch(self, rec):
        """Refresh updated_at only (derived-rollup recomputation, PRD 2.10)."""
        rec["updated_at"] = self.now_iso()

    def bump(self, rec):
        """Mutation: version += 1 and updated_at refresh (PRD 2.4)."""
        rec["version"] += 1
        rec["updated_at"] = self.now_iso()


store = Store()
