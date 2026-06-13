"""In-memory data store + id/timestamp/clock helpers.

The store starts EMPTY on every process boot. Nothing is ever seeded or
preloaded — every entity is created by the test via the declared API surface.
"""

import uuid
import threading
from datetime import datetime, timezone

# A single global lock makes every request handler atomic relative to others.
LOCK = threading.RLock()

# Monotonic insertion sequence so list-ordering by created_at is stable even
# when two records share the same millisecond timestamp.
_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


class Store:
    """Per-process in-memory store. One dict per entity collection, keyed by id."""

    def __init__(self):
        self.districts = {}
        self.routes = {}
        self.stops = {}
        self.students = {}
        self.ridership_applications = {}
        self.drivers = {}
        self.driver_assignments = {}
        self.bus_trips = {}
        self.tap_events = {}
        self.parent_notifications = {}
        self.missed_bus_reports = {}

        # Server wall clock for the missed-bus window. None => use real time.
        self.current_utc = None


DB = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Request id starting with 'req_' (PRD §2.2)."""
    return "req_" + uuid.uuid4().hex


def iso_now():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    return _format_iso(datetime.now(timezone.utc))


def _format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_clock():
    """Current server wall-clock UTC datetime used by the missed-bus window."""
    if DB.current_utc is not None:
        return DB.current_utc
    return datetime.now(timezone.utc)
