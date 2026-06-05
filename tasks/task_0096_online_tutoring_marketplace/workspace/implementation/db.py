"""In-memory data store. Starts EMPTY on every boot — no seeding, no preload.

All state is held in plain dicts keyed by id. Nothing is persisted to disk;
a fresh process begins with empty collections, which is exactly what the
per-test-server harness requires.
"""
import threading
import uuid
from datetime import datetime, timezone


# One dict per entity collection, keyed by id.
subjects = {}
commission_policies = {}
tutors = {}
credentials = {}
subject_tags = {}
parent_accounts = {}
students = {}
bookings = {}
sessions = {}
settlements = {}
refund_cases = {}

# Monotonic creation sequence so list endpoints can sort by created_at ascending
# deterministically even when two rows share the same millisecond timestamp.
_seq_counter = 0
_seq_lock = threading.Lock()

# Deterministic UTC clock (PRD 3.11). Defaults to the real now until the test
# harness sets it via POST /_clock/set.
_clock = {"now": datetime.now(timezone.utc)}

# Global lock so each request mutates the store atomically (immediate
# consistency, PRD 2.6).
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


def now_iso():
    """Current deterministic clock as an ISO 8601 string with 3 fractional digits."""
    return iso_millis(_clock["now"])


def iso_millis(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def get_clock():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt
