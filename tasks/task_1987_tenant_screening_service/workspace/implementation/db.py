"""In-memory data store. Fresh on every process boot — no seeding."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.landlords = {}
        self.jurisdiction_rules = {}
        self.criteria = {}
        self.applicants = {}
        self.applications = {}
        self.reports = {}
        self.records = {}
        self.income_verifications = {}
        self.guarantors = {}
        self.notices = {}
        self.disputes = {}
        self.audit_runs = {}
        # Logical clock: server startup default before any set call.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()
