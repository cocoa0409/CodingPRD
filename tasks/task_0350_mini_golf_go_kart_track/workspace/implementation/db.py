"""In-memory data store. All collections start empty on every boot.

NO seeding, NO preloading. Every entity is created via the API surface.
"""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.venues = {}
        self.attractions = {}
        self.pricing_plans = {}
        self.heats = {}
        self.tee_sessions = {}
        self.guests = {}
        self.waivers = {}
        self.wallets = {}
        self.combo_passes = {}
        self.party_groups = {}
        self.bookings = {}
        # Monotonic per-resource creation sequence so created_at ties are
        # broken deterministically (timestamps can collide within a ms).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
