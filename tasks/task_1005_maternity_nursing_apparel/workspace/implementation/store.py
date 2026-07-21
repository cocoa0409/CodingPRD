"""In-memory data store. Starts empty on every process boot — no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

# Logical-clock startup default (never falls back to wall-clock time).
DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.customers = {}
        self.products = {}
        self.variants = {}
        self.fit_profiles = {}
        self.orders = {}
        self.rentals = {}
        self.subscriptions = {}
        self.capsules = {}
        self.returns = {}
        self.ledger = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def seq(self):
        return next(self._seq)


store = Store()
