"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
All record timestamps (created_at, updated_at, recorded_at, placed_at,
withdrawn_at, ...) are stamped from the logical clock, which defaults to
exactly 2026-05-01T00:00:00Z and never falls back to wall-clock time.
"""
import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.growers = {}
        self.buyers = {}
        self.lots = {}
        self.lab_tests = {}
        self.runs = {}
        self.dryers = {}
        self.batches = {}
        self.bins = {}
        self.placements = {}
        self.withdrawals = {}
        self.fumigations = {}
        self.contracts = {}
        self.shipments = {}
        self.settlements = {}
        self.byproduct_sales = {}
        self.clock = DEFAULT_CLOCK
        self.seq = itertools.count(1)


store = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Canonical clock echo: whole seconds unless sub-second precision exists."""
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += "." + ("%06d" % dt.microsecond).rstrip("0")
    return base + "Z"


def now_ts():
    return fmt_ts3(store.clock)


def parse_iso(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def stamp(rec):
    """Initialize system-managed common fields on a new record."""
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next(store.seq)
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and increment version."""
    rec["updated_at"] = now_ts()
    rec["version"] += 1
