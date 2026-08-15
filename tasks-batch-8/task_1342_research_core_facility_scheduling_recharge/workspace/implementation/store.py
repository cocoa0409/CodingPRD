"""In-memory data store. Everything lives in module-level dicts keyed by id;
restarting the process wipes all state. No seeding — the store starts empty.

The logical clock defaults to exactly 2026-08-01T00:00:00Z and is only ever
moved by POST /_clock/set_current_utc; it never falls back to wall time.
"""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock (test-driving). Startup default: 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # monotonic insertion sequence for stable ordering

        self.users = {}
        self.instruments = {}
        self.training_records = {}
        self.grants = {}
        self.rate_sets = {}
        self.bookings = {}
        self.usage_logs = {}
        self.batches = {}
        self.entries = {}
        self.applications = {}
        self.awards = {}
        self.contracts = {}
        self.downtime_events = {}
        self.publications = {}
        self.fiscal_years = {}


store = Store()


def now():
    """Current logical time (aware UTC datetime)."""
    return store.clock


def today():
    """Current logical date (UTC date of the logical clock)."""
    return store.clock.date()


def next_seq():
    store.seq += 1
    return store.seq
