"""In-memory data store + logical clock.

Storage is pure in-process Python dicts keyed by id. Nothing is persisted to
disk and nothing is seeded at import time; every entity is created by the
declared API surface. A fresh process therefore starts with an empty store.
"""

import datetime
import uuid

from constants import CLOCK_DEFAULT_UTC


def _parse_iso(s):
    """Parse an ISO-8601 instant (accepts trailing 'Z') into aware UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.sellers = {}
        self.properties = {}
        self.offers = {}
        self.assessments = {}
        self.repair_line_items = {}
        self.transactions = {}
        self.resales = {}
        # logical clock — starts at the fixed default, never wall-clock
        self.clock = _parse_iso(CLOCK_DEFAULT_UTC)

    # ---- ids & timestamps ----
    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        """Current logical-clock instant (aware UTC)."""
        return self.clock

    def set_clock(self, iso_str):
        self.clock = _parse_iso(iso_str)


def iso_millis(dt):
    """Format an aware datetime as ISO-8601 UTC with exactly 3 fractional digits + 'Z'."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


# Singleton store for this process. Created empty; no seeding.
store = Store()
