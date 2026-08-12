"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding of any kind.
The logical clock defaults to 2026-05-01T00:00:00Z and only moves when the
test-driving endpoint sets it; it never falls back to wall-clock time.
"""

from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        # entity collections (insertion-ordered dicts keyed by id)
        self.service_lines = {}
        self.surgeons = {}
        self.rooms = {}
        self.blocks = {}
        self.cases = {}
        self.coverages = {}
        self.slots = {}
        self.requests = {}
        self.reports = {}
        self.reviews = {}
        self.votes = {}
        # monotonically increasing counters
        self.insert_seq = 0
        self.sched_seq = 0
        # logical clock (timezone-aware UTC datetime)
        self.clock = self._parse_dt(DEFAULT_CLOCK_ISO)

    @staticmethod
    def _parse_dt(value):
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def next_insert_seq(self):
        self.insert_seq += 1
        return self.insert_seq

    def next_sched_seq(self):
        self.sched_seq += 1
        return self.sched_seq

    def reset(self):
        self.__init__()


db = Store()
