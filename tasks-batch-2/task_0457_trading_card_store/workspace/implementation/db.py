"""In-memory data store.

PRD §2.5: every (non-ledger) entity carries id (UUID, no prefix), created_at,
updated_at (ISO 8601 UTC, 3 fractional digits), and version (integer, starts at
its initial value on creation, +1 on every mutation). The store-credit ledger is
the exception: a ledger row carries only id and created_at (append-only log).

PRD §3.8: the system runs on a logical clock. At server startup the clock reads
exactly 2026-01-01T00:00:00Z and holds there until a StoreManager sets it; it
never falls back to wall-clock time.

Storage is in-memory only. The store starts empty on every boot — nothing is
seeded, preloaded, or hardcoded. Tests build all state via the API.
"""

import uuid
from datetime import datetime, timezone

# Logical clock default (PRD §3.8). State is wiped on every process start.
DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_now = DEFAULT_CLOCK

# One dict per entity collection, keyed by id.
customers = {}
inventory_items = {}
buylist_submissions = {}
buylist_lines = {}
release_products = {}
pre_orders = {}
events = {}
registrations = {}
pairings = {}
grading_submissions = {}
consignment_cases = {}
ledger_rows = {}

# Monotonic creation sequence so creation order is total even when timestamps
# (capped at millisecond precision) collide.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    """PRD §2.5: id is a UUID with no type prefix."""
    return str(uuid.uuid4())


def get_clock():
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
    return iso(get_clock())


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
