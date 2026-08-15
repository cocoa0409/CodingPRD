"""In-memory data store. Store starts empty on every boot; no seeding."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.titles = {}
        self.vendors = {}
        self.test_plans = {}
        self.assignments = {}
        self.builds = {}
        self.bugs = {}
        self.packages = {}
        self.checklists = {}
        self.findings = {}
        self.filings = {}
        self.packs = {}
        self.windows = {}
        self.blackouts = {}
        self.hotfixes = {}
        # Logical clock: fixed startup default, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()
