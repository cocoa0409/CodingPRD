"""In-memory data store. Pure dicts keyed by id. No persistence, no seeding.

The store must start empty on every process boot -- the test harness kills
and relaunches the server via start.sh before every single test.
"""

DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00.000Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.hazard_plans = {}
        self.pods = {}
        self.staff_members = {}
        self.shift_assignments = {}
        self.countermeasures = {}
        self.inventory_lots = {}
        self.allocation_requests = {}
        self.dispensing_events = {}
        self.drills = {}
        self.situation_reports = {}
        # logical clock, stored as an ISO8601 string
        self.current_clock_iso = DEFAULT_CLOCK_ISO
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
