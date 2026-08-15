"""In-memory data store, logical clock, and id/timestamp helpers.

Storage is in-memory only (plain dicts keyed by id). The store starts empty
on every boot; nothing is seeded. All platform time comes from the logical
clock (PRD §2.4): the startup default is exactly 2026-08-01T00:00:00Z and the
clock is only ever moved by POST /api/_clock/set_current_utc — wall-clock time
is consulted solely for the response-envelope api_request_timestamp.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

LOGICAL_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq_counter = itertools.count(1)
_logical_now = [LOGICAL_START]
_wall_last = [None]


class Store:
    """One dict per entity collection. Instantiated once per process; a fresh
    process (per-test-server reboot) therefore starts completely empty."""

    def __init__(self):
        self.clients = {}
        self.facilities = {}
        self.equipment_lines = {}
        self.ingredients = {}
        self.products = {}
        self.product_ingredients = {}
        self.visits = {}
        self.findings = {}
        self.agreements = {}
        self.invoices = {}
        self.certificates = {}
        self.certificate_products = {}
        self.holiday_windows = {}


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def logical_now():
    return _logical_now[0]


def set_logical_now(dt):
    _logical_now[0] = dt


def fmt3(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_logical(dt):
    """Serialize a domain datetime: no fractional part for whole-second values
    (echoes inputs like 2026-08-02T10:00:00Z), three fractional digits when the
    value carries sub-second precision."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_now():
    """Strictly increasing wall-clock timestamp for the envelope meta."""
    now = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _wall_last[0] = now
    return fmt3(now)


def stamp_now():
    """created_at/updated_at stamp: the logical clock, three fractional digits."""
    return fmt3(logical_now())


def touch(entity):
    """Refresh updated_at and bump version on every mutation (PRD §2.4)."""
    entity["updated_at"] = stamp_now()
    entity["version"] = int(entity.get("version", 1)) + 1


def new_common(entity):
    """Stamp the full common field set on a freshly created entity."""
    entity["id"] = new_id()
    entity["created_at"] = stamp_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity
