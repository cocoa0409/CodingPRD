"""In-memory data store and server-owned logical clock.

Storage is process-local Python dicts keyed by id. Every start.sh re-launch
gets a completely empty store — nothing is seeded or preloaded anywhere.
"""

import threading
import time
from datetime import datetime, timezone

# Serializes all request handling so concurrent traffic can never observe a
# torn read-modify-write of the in-memory store.
lock = threading.RLock()

# Entity stores: id -> entity dict. All dicts are directly JSON-serializable.
parties = {}
fairs = {}
venue_slots = {}
agreements = {}
stock_lines = {}
bookings = {}
sessions = {}
tickets = {}
preorders = {}
sales = {}
reconciliations = {}
return_authorizations = {}
payouts = {}
media_blasts = {}

# Server-owned logical clock (PRD section 2.5). Never reads wall-clock time;
# advances only via POST /_clock/set_current_utc.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
logical_clock = CLOCK_DEFAULT

# Monotonic millisecond source so created_at is unique and strictly ordered
# even for back-to-back writes inside the same wall-clock millisecond.
_last_ts_ms = 0


def now_iso():
    """ISO-8601 UTC timestamp with exactly three fractional digits."""
    global _last_ts_ms
    ms = int(time.time() * 1000)
    if ms <= _last_ts_ms:
        ms = _last_ts_ms + 1
    _last_ts_ms = ms
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)
