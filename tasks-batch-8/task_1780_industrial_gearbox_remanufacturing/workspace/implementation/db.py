"""In-memory data store, the shop logical clock, id/timestamp helpers.

No disk persistence and no seeding: every table starts empty on boot and all
entities are constructed through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.8: at server startup the logical clock reads exactly 2026-08-01T00:00:00Z.
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq_counter = itertools.count(1)


class Store:
    """All entity tables plus the logical clock. Instantiated empty."""

    def __init__(self):
        self.customers = {}
        self.units = {}
        self.orders = {}
        self.findings = {}
        self.decisions = {}
        self.assembly_records = {}
        self.run_in_tests = {}
        self.loaner_units = {}
        self.loaner_assignments = {}
        self.shipments = {}
        self.warranty_claims = {}
        # The single logical clock (PRD 2.8). All date/time behavior reads it.
        self.clock = _CLOCK_START


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def now_iso3():
    """Logical clock formatted ISO 8601 UTC with exactly three fractional digits.

    Used for created_at / updated_at (PRD 2.4) and meta.api_request_timestamp.
    """
    dt = store.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso():
    """Logical clock formatted ISO 8601 UTC, dropping a zero fraction.

    Used for completed_at_utc and the clock endpoint's current_utc so a clock
    set to "2026-08-02T00:00:00Z" reads back exactly that string.
    """
    dt = store.clock
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def touch(entity):
    """Refresh updated_at and bump version on a mutable entity (PRD 2.4)."""
    entity["updated_at"] = now_iso3()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity (PRD 2.4)."""
    ts = now_iso3()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def new_append_only(entity):
    """TeardownFinding is append-only: id + created_at, no updated_at/version."""
    entity["created_at"] = now_iso3()
    entity["_seq"] = next_seq()
    return entity


def set_field(entity, key, value):
    """Assign a field, touching the entity only when the value actually changes."""
    if entity.get(key) != value:
        entity[key] = value
        touch(entity)


def parse_iso_dt(value):
    """Parse an ISO 8601 datetime string (trailing Z allowed) to aware UTC."""
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Parse an ISO 8601 calendar date string (YYYY-MM-DD) to a date."""
    from datetime import date as _date
    return _date.fromisoformat(value.strip())
