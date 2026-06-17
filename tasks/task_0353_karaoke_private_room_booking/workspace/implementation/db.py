"""In-memory data store (PRD §2.4).

ALL storage is process-local Python dicts keyed by id. There is no SQLite,
no JSON-on-disk, no /tmp cache. A fresh process (every start.sh invocation)
starts with completely empty collections. NOTHING is seeded or preloaded —
tests build all state through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone


# One dict per entity collection, keyed by id.
venues = {}
room_types = {}
rooms = {}
group_packages = {}
customers = {}
reservations = {}
extensions = {}
songs = {}
queue_entries = {}
fb_orders = {}
payments = {}

# Venue-scoped logical clock (PRD §2.9). Maps venue_id -> ISO8601 string set
# via /venues/{venue_id}/_clock/set. If unset, current_utc falls back to real
# wall-clock UTC.
venue_clocks = {}

# Global lock to keep multi-step mutations atomic.
lock = threading.RLock()


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
