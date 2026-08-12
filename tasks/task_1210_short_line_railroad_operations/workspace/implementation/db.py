"""In-memory data store. Fresh process => fresh, empty store. No seeding."""

from datetime import datetime, timezone

# Logical clock default epoch pinned by PRD section 2.4:
# "At server startup the clock reads exactly 2026-05-01T00:00:00Z"
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.now = CLOCK_DEFAULT
        self.seq = 0  # global monotonic creation sequence (stable ordering)
        self.fra_seq = 0  # FRA report number sequence
        self.customers = {}
        self.sidings = {}
        self.car_orders = {}
        self.railcars = {}
        self.switch_jobs = {}
        self.movements = {}
        self.interchange_events = {}
        self.car_hire_statements = {}
        self.waybills = {}
        self.revenue_divisions = {}
        self.track_segments = {}
        self.track_inspections = {}
        self.crew_members = {}
        self.crew_calls = {}
        self.incidents = {}
        self.grant_projects = {}
        self.grant_milestones = {}

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_fra_number(self):
        self.fra_seq += 1
        return "FRA-%06d" % self.fra_seq


store = Store()
