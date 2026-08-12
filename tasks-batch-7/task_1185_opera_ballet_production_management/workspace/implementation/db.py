"""In-memory data store. Starts completely empty on every boot — no seeding.

All state lives in module-level dicts keyed by id and dies with the process,
which is exactly what the per-test-server isolation model requires.
"""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        # Logical clock (PRD section 2.5): starts at exactly 2026-05-01T00:00:00Z
        # and only moves via POST /_clock/set_current_utc. Never wall-clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.partner_companies = {}
        self.productions = {}
        self.build_items = {}
        self.co_production_shares = {}
        self.artists = {}
        self.contracts = {}
        self.roles = {}
        self.cast_assignments = {}
        self.rehearsal_rooms = {}
        self.rehearsal_calls = {}
        self.call_participants = {}
        self.stage_slots = {}
        self.performances = {}
        self.seat_inventories = {}
        self.surtitle_tracks = {}
        self.rental_offers = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
