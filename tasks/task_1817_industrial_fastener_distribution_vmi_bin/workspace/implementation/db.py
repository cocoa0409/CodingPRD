"""In-memory data store, logical clock, id/timestamp helpers.

The store starts completely empty on every boot. No entity seeding anywhere.
"""

import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    txt = s.strip()
    if txt.endswith(("Z", "z")):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # monotonic creation sequence (stable created_at ordering)
        self.sites = {}
        self.parts = {}
        self.xrefs = {}
        self.agreements = {}
        self.routes = {}
        self.stops = {}
        self.orders = {}
        self.certs = {}
        self.kitjobs = {}
        # logical clock: never falls back to wall-clock time
        self.clock_dt = _parse_iso(DEFAULT_CLOCK_ISO)
        self.clock_raw = DEFAULT_CLOCK_ISO

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def parse_iso(s):
    """Parse an ISO 8601 string to an aware UTC datetime. Raises ValueError."""
    return _parse_iso(s)


def touch(entity):
    """Every mutation bumps version and refreshes updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()
