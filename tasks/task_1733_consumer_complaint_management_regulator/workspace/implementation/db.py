"""In-memory data store and logical clock.

The store starts byte-empty on every boot: no seeding, no persistence.
All records are plain Rec instances held in module-level dicts keyed by id.
"""
from datetime import datetime, timezone


class Rec:
    """Attribute-access record."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self):  # pragma: no cover
        return f"Rec({self.__dict__!r})"


class Store:
    def __init__(self):
        # entity tables: id -> Rec
        self.products = {}
        self.channels = {}
        self.categories = {}
        self.templates = {}
        self.complaints = {}
        self.events = {}
        self.referrals = {}
        self.rcas = {}
        self.decisions = {}
        self.reviews = {}
        self.escalations = {}
        self.snapshots = {}
        # business-code indexes
        self.product_by_code = {}
        self.channel_by_code = {}
        self.category_by_code = {}
        self.template_by_key = {}
        # monotonic sequence for deterministic ordering / "latest" resolution
        self.seq = 0
        # logical clock: startup default per PRD §2.5, never wall-clock
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


store = Store()
