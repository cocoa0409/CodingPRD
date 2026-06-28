"""In-memory data store. All state lives in module-level dicts keyed by id.

A fresh process (each start.sh re-invocation) wipes everything. No seeding,
no preload, no on-disk persistence.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity collections — id -> dict
# ---------------------------------------------------------------------------
sessions = {}
students = {}
photos = {}
packages = {}
photo_orders = {}
order_lines = {}
retouch_orders = {}
shipments = {}
backdrops = {}
photographers = {}
capture_slots = {}

# Monotonic sequence to give each row a stable creation ordinal for tie-breaks
# and creation-order sorting (independent of timestamp collisions).
_seq_counter = itertools.count(1)

# A single global lock to keep multi-step mutations atomic within a process.
LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock. Startup default per PRD §2.10. Never falls back to wall clock.
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _DEFAULT_CLOCK}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def iso_now():
    """Server real timestamp for created_at/updated_at and meta — ISO 8601 UTC,
    three fractional digits (PRD §2.4 / §2.2). Independent of the logical clock,
    which governs only time-sensitive *comparisons* (gallery expiry)."""
    return format_iso(datetime.now(timezone.utc))


def format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
