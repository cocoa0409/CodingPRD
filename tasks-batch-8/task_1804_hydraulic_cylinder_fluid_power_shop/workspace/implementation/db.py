"""In-memory data store + logical clock.

Storage is process-local Python dicts only. The store starts completely empty
on every boot; every entity is created through a declared endpoint. No seeding,
no files, no SQLite, no /tmp caches.
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.5)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_iso8601(value):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts a trailing 'Z' or explicit offsets; naive values are treated as UTC.
    Raises ValueError on unparsable input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt):
    """Render an aware UTC datetime as ISO 8601 with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    return "%s.%03dZ" % (base, millis)


class LogicalClock:
    """The system logical clock. Starts at exactly 2026-08-01T00:00:00Z and
    never falls back to wall-clock time."""

    def __init__(self):
        self._current = parse_iso8601(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._current

    def now_iso(self):
        return format_ts(self._current)

    def set(self, dt):
        self._current = dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Entity stores
# ---------------------------------------------------------------------------

ENTITY_STORES = [
    "shops",
    "customers",
    "technicians",
    "seal_kits",
    "cylinders",
    "work_orders",
    "teardown_reports",
    "quotes",
    "inventory_items",
    "stock_reservations",
    "test_bays",
    "pressure_tests",
    "certificates",
    "exchange_units",
    "field_service_jobs",
]


class Store:
    def __init__(self):
        for name in ENTITY_STORES:
            setattr(self, name, {})
        # monotonic insertion sequence used as a stable tie-breaker when
        # several entities share the same logical created_at instant
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Module-level singletons (fresh per process boot).
DB = Store()
CLOCK = LogicalClock()


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Per PRD 2.4: any mutation refreshes updated_at and increments version."""
    entity["version"] += 1
    entity["updated_at"] = CLOCK.now_iso()


def make_entity(fields):
    """Create a fresh entity dict with common fields per PRD 2.4."""
    now = CLOCK.now_iso()
    entity = dict(fields)
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = DB.next_seq()
    return entity


def serialize(entity):
    """Strip internal bookkeeping keys before returning an entity."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sorted_entities(store_dict):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return sorted(store_dict.values(), key=lambda e: (e["created_at"], e["_seq"]))
