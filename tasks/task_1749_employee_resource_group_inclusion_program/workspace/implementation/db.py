"""In-memory data store. Everything lives in process memory; a fresh process
starts with a completely empty store (no seeding, no files, no caches)."""
import threading
from datetime import datetime, timezone

STORE = {
    "programs": {},
    "sponsors": {},
    "groups": {},
    "memberships": {},
    "terms": {},
    "funding_requests": {},
    "venues": {},
    "events": {},
    "rsvps": {},
    "surveys": {},
    "responses": {},
    "engagements": {},
}

# Single global re-entrant lock serializes all request handling so concurrent
# test traffic cannot interleave multi-step mutations.
LOCK = threading.RLock()

_seq = 0


def next_seq():
    """Monotonic insertion sequence; stable tie-breaker for created_at ordering."""
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# Logical clock. Starts at exactly 2026-08-01T00:00:00Z before any set call;
# never reads wall-clock time. All entity timestamps derive from this clock.
# ---------------------------------------------------------------------------
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt
