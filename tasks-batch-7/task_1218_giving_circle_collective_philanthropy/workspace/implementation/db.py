"""In-memory data store. Fresh on every boot; nothing is seeded."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.circles = {}
        self.cycles = {}
        self.members = {}
        self.memberships = {}
        self.contributions = {}
        self.nonprofits = {}
        self.nominations = {}
        self.site_visits = {}
        self.learning_sessions = {}
        self.ballots = {}
        self.awards = {}
        self.payouts = {}
        self.reports = {}
        self.rollover_decisions = {}
        # Logical clock: never falls back to wall-clock time.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()
