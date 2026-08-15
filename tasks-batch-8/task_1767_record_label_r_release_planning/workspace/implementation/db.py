"""In-memory data store. Fresh per process; no persistence of any kind."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.labels = {}
        self.artists = {}
        self.deal_memos = {}
        self.contracts = {}
        self.recoupment_accounts = {}
        self.recording_projects = {}
        self.milestones = {}
        self.tracks = {}
        self.releases = {}
        self.distributors = {}
        self.deliveries = {}
        self.beats = {}
        self.campaigns = {}
        self.tour_supports = {}
        self.tour_expenses = {}
        self.revenue_reports = {}
        self.royalty_runs = {}
        self.royalty_statements = {}
        # Monotonic insertion sequence for stable ordering on tied created_at.
        self._seq = 0
        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical timestamp, ISO 8601 UTC with three fractional digits."""
    return db.clock.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (db.clock.microsecond // 1000)


def today():
    """The calendar date of the logical clock."""
    return db.clock.date()
