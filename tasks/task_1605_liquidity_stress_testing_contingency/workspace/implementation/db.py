"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.seq = 0                  # global insertion counter (stable ordering)
        self.clock = INITIAL_CLOCK    # logical clock (never wall-clock for business data)
        self.scenarios = {}
        self.runs = {}
        self.assets = {}
        self.funding_sources = {}
        self.metrics = {}
        self.readings = {}
        self.posture_snapshots = {}
        self.posture_seq = 0
        self.playbooks = {}
        self.actions = {}
        self.lines = {}
        self.pledges = {}
        self.limits = {}
        self.breaches = {}
        self.intraday_snapshots = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def mint_id():
    return str(uuid.uuid4())
