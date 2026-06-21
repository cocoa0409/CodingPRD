"""In-memory data store.

Storage is plain Python dicts keyed by entity id. Nothing is seeded or
preloaded at import time — every record is created by a test via the declared
API surface. Because the process is killed and re-launched (via start.sh)
before every test under per-test-server isolation, module re-import wipes all
of this state and guarantees a fresh boot.
"""

import threading
import uuid
from datetime import datetime, timezone


# One dict per entity type, keyed by id (UUID string, no prefix).
landlords = {}
tenants = {}
properties = {}
agreements = {}
rent_payments = {}
maintenance_tickets = {}
option_exercises = {}
mortgages = {}

# Single global lock guarding all mutations; the API is single-threaded in
# spirit (immediate consistency) but Flask may serve concurrent requests.
LOCK = threading.RLock()

# Server logical clock (test-driving). Defaults to real wall-clock UTC until a
# test pins it via POST /_clock/set_current_utc.
_current_clock = None  # datetime or None


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp with exactly three fractional digits (Z)."""
    return iso_millis(datetime.now(timezone.utc))


def iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_clock(dt):
    global _current_clock
    _current_clock = dt


def current_clock():
    """The server's logical 'now' for temporal business rules."""
    if _current_clock is not None:
        return _current_clock
    return datetime.now(timezone.utc)
