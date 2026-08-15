"""In-memory data store. The store starts empty on every boot — no seeding."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Entity collections, keyed by id.
        self.plan_years = {}
        self.territories = {}
        self.assignment_rules = {}
        self.accounts = {}
        self.reps = {}
        self.ramp_schedules = {}
        self.rep_assignments = {}
        self.allocations = {}
        self.submissions = {}
        self.reconciliation_runs = {}
        self.change_requests = {}
        self.credit_events = {}
        self.disputes = {}
        # Logical clock: default 2026-08-01T00:00:00Z, never falls back to wall time.
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def now_iso():
    """Current logical timestamp, ISO 8601 UTC with three fractional digits."""
    dt = store.logical_clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_today():
    """Date part of the logical clock."""
    return store.logical_clock.date()


def request_timestamp():
    """Timestamp for meta envelope — logical clock (server-generated)."""
    return now_iso()
