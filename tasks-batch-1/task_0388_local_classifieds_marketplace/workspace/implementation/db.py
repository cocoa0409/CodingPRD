"""In-memory data store. NO seeding — every dict starts empty on each boot.

State is wiped by a fresh process (the test harness restarts the server before
every test). Storage is pure Python dicts keyed by id; nothing is persisted to
disk.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Entity tables keyed by id (or slug for categories).
        self.members = {}
        self.categories = {}          # keyed by slug
        self.listings = {}
        self.conversations = {}
        self.messages = {}
        self.offers = {}
        self.safe_trade_spots = {}
        self.meetups = {}
        self.flags = {}
        self.saved_searches = {}
        self.alerts = {}

        # Monotonic creation sequence so created_at ties resolve deterministically
        # (oldest first) even when several records share the same logical clock.
        self._seq = 0

        # Server-held logical clock (§2.10). Default to the Unix epoch in UTC so
        # the system has a deterministic starting instant before any /_clock call.
        self.current_clock = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Current logical clock as a timezone-aware UTC datetime."""
        return self.current_clock


# Module-level singleton store. Created empty; never seeded.
store = Store()
