"""In-memory data store + test-driving server clock.

Storage is purely in-memory (dicts keyed by id). The store starts EMPTY on
every boot; nothing is seeded. Per-test-server isolation wipes all state by
re-launching the process, so a fresh boot must start clean.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.categories = {}
        self.sla_policies = {}
        self.assignment_groups = {}
        self.tickets = {}
        self.problems = {}
        self.known_errors = {}
        self.kb_articles = {}
        self.change_requests = {}
        self.cab_votes = {}
        self.csat_surveys = {}
        self.assets = {}

        # Logical (test-driving) server clock. Defaults to real wall-clock now,
        # but tests drive it deterministically via /_clock/set and /_clock/advance.
        self._clock = datetime.now(timezone.utc)
        self.lock = threading.RLock()

    # --- clock ---
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    def advance_clock(self, minutes):
        from datetime import timedelta

        self._clock = self._clock + timedelta(minutes=minutes)
        return self._clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Single global store instance — created empty at import, never seeded.
store = Store()
