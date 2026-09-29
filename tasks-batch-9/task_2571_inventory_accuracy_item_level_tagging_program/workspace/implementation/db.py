"""In-memory data store.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here — every entity is created by clients through the declared
endpoints.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4 — the logical clock reads this instant before it is ever set.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_seq = itertools.count(1)
_lock = threading.RLock()

COLLECTIONS = (
    "categories",
    "stores",
    "vendors",
    "counter_firms",
    "items",
    "stock_positions",
    "tag_batches",
    "count_schedules",
    "count_tasks",
    "count_lines",
    "investigations",
    "adjustments",
    "shrink_periods",
    "physical_inventories",
    "physical_inventory_lines",
)


class _DB(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = _parse_instant(DEFAULT_CLOCK_UTC)

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = _parse_instant(DEFAULT_CLOCK_UTC)


def _parse_instant(text):
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


db = _DB()

lock = _lock


def new_id():
    """Server-generated UUID, no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence; used as a stable tiebreak for ordering."""
    with _lock:
        return next(_seq)


def format_instant(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def format_clock_instant(value):
    """
    The logical clock's own spelling of an instant.

    PRD 2.4 pins three fractional digits for `created_at`, `updated_at` and the
    envelope's `api_request_timestamp` only, and states that before it is ever
    set the clock reads exactly `2026-08-01T00:00:00Z`.  Fields stamped with
    "the current logical-clock instant" therefore carry the clock's spelling: a
    fractional part only when the instant actually has one.
    """
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        return format_instant(value)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_now_iso():
    """Envelope timestamp (meta.api_request_timestamp)."""
    return format_instant(datetime.now(timezone.utc))


def row_stamp_iso():
    """
    Row-minting timestamp (created_at / updated_at).

    PRD 2.4: "Time in this domain is never read from the wall clock." — so the
    row stamps come off the logical clock too, in the three-fractional-digit
    spelling PRD 2.4 pins for these two fields.
    """
    return format_instant(db.clock)


def clock_now():
    """The logical clock instant — never the wall clock (PRD 2.4)."""
    return db.clock


def clock_now_iso():
    return format_clock_instant(db.clock)


def clock_today():
    return db.clock.astimezone(timezone.utc).date()


def set_clock(value):
    db.clock = value.astimezone(timezone.utc)


__all__ = [
    "db",
    "lock",
    "new_id",
    "next_seq",
    "format_instant",
    "format_clock_instant",
    "wall_now_iso",
    "row_stamp_iso",
    "clock_now",
    "clock_now_iso",
    "clock_today",
    "set_clock",
    "timedelta",
    "DEFAULT_CLOCK_UTC",
]
