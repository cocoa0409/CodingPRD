"""In-memory data store. Everything lives in process memory; a fresh process
starts completely empty (no seeding, no disk persistence)."""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.participants = {}
        self.generators = {}
        self.operating_days = {}
        self.price_nodes = {}
        self.offers = {}
        self.telemetry = {}
        self.outages = {}
        self.statements = {}
        self.lines = {}
        self.disputes = {}
        self.awards = {}
        self.obligations = {}
        self.events = {}
        self.postings = {}
        self.margin_calls = {}
        # monotonic insertion counter for stable created_at tie-breaking
        self.seq = 0
        # logical clock: startup default is exactly 2026-08-01T00:00:00Z
        self.clock_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_str = "2026-08-01T00:00:00Z"
        # monotonic wall-clock timestamp tracker for created_at/updated_at
        self.last_ts = None

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
