"""In-memory data store for the custom harvesting API.

The store starts empty on every boot — no seeding, no preloading. Every
entity a test needs is constructed through the declared API surface.
"""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Entity tables, keyed by id (UUID string, no prefix)
        self.seasons = {}
        self.contracts = {}
        self.route_stops = {}
        self.machines = {}
        self.crew_members = {}
        self.machine_assignments = {}
        self.delivery_tickets = {}
        self.settlements = {}
        self.lodging_reservations = {}
        self.lodging_sites = {}
        # Monotonic insertion counter used as a stable tiebreaker so list
        # ordering by created_at ascending is deterministic even when two
        # resources are created within the same millisecond.
        self.creation_counter = 0
        # Logical clock state. Before any call to set_current_utc the clock
        # reads exactly 2026-08-01T00:00:00Z and never falls back to
        # wall-clock time.
        self.logical_clock_iso = "2026-08-01T00:00:00Z"

    def next_creation_index(self):
        self.creation_counter += 1
        return self.creation_counter


db = Store()
