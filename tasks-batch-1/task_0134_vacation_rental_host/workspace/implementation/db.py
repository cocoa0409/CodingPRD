"""In-memory data store. Wiped on every process start — no seeding, no persistence.

All collections are plain dicts keyed by entity id. The logical clock is held here
too. Nothing is pre-populated; tests build every entity via the API surface.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.hosts = {}
        self.guests = {}
        self.listings = {}
        self.rate_plans = {}
        self.channel_connections = {}
        self.calendar_blocks = {}
        self.bookings = {}
        self.screening_results = {}
        self.security_deposits = {}
        self.damage_claims = {}
        self.payouts = {}
        self.imported_reservations = {}
        # Logical test-driving clock (PRD §3.10). Defaults to real now until set.
        self.current_utc = datetime.now(timezone.utc)
        # Monotonic insertion sequence so created_at ascending ordering is stable
        # even when two records share an identical timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single global store instance, fresh per process boot.
db = Store()
