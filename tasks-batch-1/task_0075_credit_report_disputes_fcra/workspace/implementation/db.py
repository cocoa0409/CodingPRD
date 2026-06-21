from datetime import datetime, timezone


class DB:
    """In-memory store. Reset on every process boot. No seeding."""

    def __init__(self):
        self.consumers = {}
        self.furnishers = {}
        self.credit_files = {}
        self.tradelines = {}
        self.disputes = {}
        self.reverifications = {}
        self.security_freezes = {}
        self.complaints = {}
        self.notifications = {}
        self.reage_events = {}
        # logical server clock; starts at real "now" but is fully test-driven
        self.clock = datetime.now(timezone.utc)
        # monotonic sequence used to break creation-time ties deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
