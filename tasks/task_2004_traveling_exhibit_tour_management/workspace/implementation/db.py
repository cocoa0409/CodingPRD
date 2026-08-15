"""In-memory data store, logical clock, id and timestamp helpers.

The store starts empty on every boot — no seeding. All timestamps are
ISO 8601 UTC with three fractional digits. created_at values are strictly
monotonic across the process so the route_sequence created_at tie-break is
always decidable.
"""

import threading
import time
import uuid
from datetime import datetime, timezone

# --- entity stores (empty at boot) -----------------------------------------

tours = {}
venues = {}
stops = {}
contracts = {}
crates = {}
shipments = {}
reports = {}
claims = {}
kits = {}
certs = {}

# --- logical clock (PRD §2.4): fixed startup default, never wall-clock ------

CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# --- ids --------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())

# --- timestamps --------------------------------------------------------------

_ts_lock = threading.Lock()
_last_ms = 0


def _next_ms():
    global _last_ms
    with _ts_lock:
        n = int(time.time() * 1000)
        if n <= _last_ms:
            n = _last_ms + 1
        _last_ms = n
        return n


def iso_from_ms(n):
    dt = datetime.fromtimestamp(n / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n % 1000)


def now_iso():
    return iso_from_ms(_next_ms())


def stamp_new(resource):
    """Attach the four common system fields to a freshly created resource."""
    t = now_iso()
    resource["created_at"] = t
    resource["updated_at"] = t
    resource["version"] = 1
    return resource


def touch(resource):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    resource["updated_at"] = now_iso()
    resource["version"] += 1
    return resource


# --- datetime parsing ---------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime; None if bad."""
    if not isinstance(value, str):
        return None
    try:
        t = value.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def iso_from_dt(dt):
    """Canonical UTC rendering; whole-second instants print without fraction."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % ms
