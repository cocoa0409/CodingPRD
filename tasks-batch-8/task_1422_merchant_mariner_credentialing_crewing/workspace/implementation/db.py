"""In-memory data store and the logical clock.

Storage is process-local dicts only: no SQLite, no files, no seeding.
The store starts empty on every boot; the logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time (PRD 2.6).
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
    """Format an aware datetime as ISO-8601 UTC with three fractional digits.

    Used for the system-managed timestamps of PRD 2.4 (created_at,
    updated_at) and the envelope's api_request_timestamp (PRD 2.2).
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt_sec(dt):
    """Format an aware datetime as ISO-8601 UTC at second precision.

    PRD 2.7 pins all datetime comparisons to second precision, and PRD 2.6
    states the clock "reads exactly 2026-08-01T00:00:00Z" — domain datetimes
    (expiry_date, sign_on_date, dues_current_until, current_utc, ...) are
    therefore rendered at second precision, echoing supplied values.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self):
        self.clock = parse_dt(DEFAULT_CLOCK_ISO)
        self.seq = 0  # monotonic creation counter, stabilises created_at ordering
        self.lock = threading.RLock()
        self.mariners = {}
        self.vessels = {}
        self.manning_slots = {}
        self.rotation_plans = {}
        self.credentials = {}
        self.sea_service_records = {}
        self.medical_certificates = {}
        self.drug_tests = {}
        self.training_courses = {}
        self.training_enrollments = {}
        self.training_budgets = {}
        self.union_halls = {}
        self.union_registrations = {}
        self.assignments = {}
        self.travel_bookings = {}

    def now_iso(self):
        return fmt_dt(self.clock)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def stamp(self, rec):
        """Set creation common fields on a fresh record (PRD 2.4)."""
        rec["_seq"] = self.next_seq()
        rec["id"] = self.new_id()
        rec["created_at"] = self.now_iso()
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1

    def bump(self, rec):
        """Mutation: version += 1 and updated_at refresh (PRD 2.4)."""
        rec["version"] += 1
        rec["updated_at"] = self.now_iso()


store = Store()
