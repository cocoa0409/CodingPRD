"""In-memory data store. Fresh and empty on every process boot — no seeding."""
import threading
from datetime import datetime, timezone

# Logical clock default per PRD §2.10 — never falls back to wall clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0                      # insertion sequence for stable sort
        self.clock = DEFAULT_CLOCK        # logical clock (datetime, UTC)
        self.airports = {}
        self.biologists = {}
        self.atc_controllers = {}
        self.regulators = {}
        self.species = {}
        self.strike_reports = {}
        self.carcass_records = {}
        self.habitat_assessments = {}
        self.mitigation_actions = {}
        self.dispersal_activities = {}
        self.take_permits = {}
        self.operational_advisories = {}
        self.runway_closures = {}
        self.annual_plans = {}
        self.training_records = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
