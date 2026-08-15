"""In-memory data store and logical clock.

The store starts completely empty on every boot -- no seeding of any kind.
The logical clock starts at exactly 2026-08-01T00:00:00Z per the PRD and is
only ever moved through POST /consumer-protection/_clock/set_current_utc.
"""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock -- never wall-clock time.
        self.now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Entity tables, keyed by id. Insertion order is creation order.
        self.consumers = {}
        self.businesses = {}
        self.complaints = {}
        self.events = {}
        self.responses = {}
        self.mediators = {}
        self.rooms = {}
        self.sessions = {}
        self.offers = {}
        self.settlements = {}
        self.payments = {}
        self.referrals = {}
        self.alerts = {}
        # complaint_id -> datetime of the latest EMBARGOED -> PUBLISHED
        # transition (drives the ROLLING_12M rating variant recency weight).
        self.published_at = {}

    def reset(self):
        self.__init__()


db = Store()
