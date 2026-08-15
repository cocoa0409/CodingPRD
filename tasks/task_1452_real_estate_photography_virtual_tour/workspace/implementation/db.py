"""In-memory data store for the Real Estate Media API.

The store starts empty on every boot. No seeding, no persistence.
"""

from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        self.markets = {}
        self.photographers = {}
        self.client_agents = {}
        self.bookings = {}
        self.checklist_items = {}
        self.addons = {}
        self.airspace_authorizations = {}
        self.asset_bundles = {}
        self.revisions = {}
        self.virtual_tours = {}
        self.license_grants = {}
        self.reschedule_events = {}
        # Logical clock: starts at 2026-08-01T00:00:00Z
        self._clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


store = Store()
