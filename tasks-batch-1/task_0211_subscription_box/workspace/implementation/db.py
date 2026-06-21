"""In-memory data store. No seeding — starts empty on every boot (per-test reboot)."""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.plans = {}
        self.products = {}
        self.subscribers = {}
        self.subscriptions = {}
        self.gift_grants = {}
        self.billing_cycles = {}
        self.box_selections = {}
        self.shipping_waves = {}
        self.allocations = {}
        self.shipments = {}
        self.wallet_entries = {}
        self.invoices = {}
        # Monotonic creation sequence used for deterministic created_at ordering.
        self._seq = itertools.count(1)
        # Simulated logical clock (PRD §3.12 test-driving). Defaults to real now.
        self._clock = datetime.now(timezone.utc)

    # ---- clock ----------------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._clock = dt.astimezone(timezone.utc)

    # ---- id / sequence --------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


db = Store()
