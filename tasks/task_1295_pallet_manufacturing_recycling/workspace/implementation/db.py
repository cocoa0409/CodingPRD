"""In-memory data store and logical clock.

State is process-local: plain dicts keyed by id, reset on every boot.
The store starts EMPTY on every launch -- no seeding anywhere.

The logical clock governs all time-dependent behavior. Startup default is
exactly 2026-08-01T00:00:00Z (PRD section 2.5); never falls back to wall time.
"""

import uuid
from datetime import datetime, timezone

# Logical clock (module-level singleton).
_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_now = _DEFAULT_CLOCK

# ISPM-15 mark sequence counter (per server lifetime).
_ht_mark_seq = 0


def now():
    """Return the current logical-clock instant (timezone-aware UTC)."""
    return _logical_now


def set_clock(dt):
    """Advance the logical clock to the given aware datetime."""
    global _logical_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _logical_now = dt.astimezone(timezone.utc)
    return _logical_now


def next_ht_mark_seq():
    global _ht_mark_seq
    _ht_mark_seq += 1
    return _ht_mark_seq


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits, e.g.
    2026-08-01T12:00:00.000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def stamp_now():
    return iso(now())


class Store:
    """Container for all entity tables. Instantiated once at module level."""

    def __init__(self):
        self.specs = {}
        self.lumber_index = {}
        self.seasonal_index = {}
        self.core_batches = {}
        self.core_units = {}
        self.repair_orders = {}
        self.inventory_lots = {}
        self.ht_runs = {}
        self.customers = {}
        self.orders = {}
        self.order_lines = {}
        self.pool_returns = {}
        self.routes = {}
        self.route_stops = {}
        self.grinding_batches = {}


db = Store()
