"""In-memory data store.

Storage is in-memory only — plain Python dicts keyed by id. There is NO seeding,
preloading, or hardcoding of any entity. Every byte of state is wiped when the
process restarts; tests build all state via API calls.
"""


class DB:
    def __init__(self):
        self.locations = {}
        self.service_types = {}
        self.products = {}
        self.rooms = {}
        self.technicians = {}
        self.members = {}
        self.memberships = {}
        self.credit_ledger = {}
        self.reservations = {}
        self.retail_sales = {}
        self.no_show_strikes = {}
        # Monotonic write sequence used as a stable tie-breaker for append order
        # (ledger entries / strikes) — never id-based ordering (PRD 3.2).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
