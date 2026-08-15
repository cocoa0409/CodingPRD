"""In-memory data store. The store starts empty on every boot: no seeding,
no preloading, no disk persistence of any kind."""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.providers = {}
        self.members = {}
        self.conflicts = {}
        self.cases = {}
        self.assignments = {}
        self.notes = {}
        self.deliberations = {}
        self.notifications = {}
        self.responses = {}
        self.external_referrals = {}
        self.focused_reviews = {}
        self.focus_groups = {}
        self.focus_group_members = {}
        # monotonic insertion counter for stable list ordering
        self.seq = itertools.count(1)
        # logical clock; PRD-mandated startup default, never wall-clock
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())
