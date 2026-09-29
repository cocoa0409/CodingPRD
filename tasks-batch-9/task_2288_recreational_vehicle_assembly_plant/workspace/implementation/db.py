"""In-memory store, logical clock and row bookkeeping.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded — every row a test needs is created through the declared API.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, has_request_context

# PRD §2.5 — the clock's value before any call.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ENTITIES = [
    "suppliers",
    "floor_plans",
    "option_items",
    "dealers",
    "unit_orders",
    "production_lines",
    "production_slots",
    "chassis_receipts",
    "component_lots",
    "unit_builds",
    "component_installations",
    "test_booths",
    "quality_inspections",
    "warranty_claims",
    "recall_campaigns",
]


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in ENTITIES:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        self.build_counter = 0


store = Store()


def now():
    """The logical clock. Every timestamp in the system is stamped from it."""
    return store.clock


def next_seq():
    return next(store._seq)


def new_id():
    return str(uuid.uuid4())


def new_row(fields=None):
    """A row carrying the four system-managed properties of PRD §2.4."""
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    if fields:
        row.update(fields)
    return row


def _touched_set():
    if has_request_context():
        if not hasattr(g, "_touched_rows"):
            g._touched_rows = set()
        return g._touched_rows
    return None


def touch(row):
    """Bump version and updated_at — at most once per row per operation (PRD §2.4)."""
    if row is None:
        return row
    seen = _touched_set()
    key = row.get("id")
    if seen is not None and key in seen:
        return row
    if seen is not None:
        seen.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()
    return row


# ---------------------------------------------------------------------------
# timestamp formatting / parsing
# ---------------------------------------------------------------------------
def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2 / §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "{}.{:03d}Z".format(dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def iso_instant(dt):
    """Domain instants: whole-second values round-trip byte-identically."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_ms(dt)


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns None when the value is not one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days_between(earlier, later):
    """Ages are whole days, fractional remainder discarded (PRD §2.5)."""
    if earlier is None or later is None:
        return 0
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def ordered(rows):
    """Default list ordering: created_at ASC (insertion sequence breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
