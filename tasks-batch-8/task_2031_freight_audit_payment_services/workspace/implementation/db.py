"""In-memory data store and logical clock.

Storage is pure Python dicts; every boot of the process starts completely empty.
No seeding of any entity happens here or anywhere else.
"""

import uuid
from datetime import datetime, date, timedelta, timezone

from errors import ApiError, ERR_INVALID_REQUEST


class Store:
    def __init__(self):
        self.clients = {}
        self.carriers = {}
        self.contracts = {}
        self.shipments = {}
        self.invoices = {}
        self.lines = {}
        self.exceptions = {}
        self.gl_accounts = {}
        self.allocations = {}
        self.runs = {}
        self.run_items = {}
        self.advices = {}
        self.fx_rates = {}
        self.claims = {}
        self.exports = {}
        # Logical clock: startup default exactly 2026-08-01T00:00:00Z; never wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # monotonic insertion counter used as a stable tie-breaker


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def _render_ts(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_iso():
    return _render_ts(STORE.clock)


def today():
    """Current logical date (date portion of the logical clock)."""
    return STORE.clock.date()


def today_str():
    return today().isoformat()


def set_clock(to_iso8601):
    dt = parse_datetime(to_iso8601)
    STORE.clock = dt
    return _render_ts(STORE.clock)


def parse_datetime(value):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(value):
    """Strictly parse a YYYY-MM-DD calendar date string -> datetime.date."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    try:
        dt = datetime.strptime(value.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        raise ValueError("invalid date")
    # strptime is lenient about some forms; enforce exact shape
    if dt.strftime("%Y-%m-%d") != value.strip():
        raise ValueError("invalid date")
    return dt.date()


def is_date_string(value):
    try:
        parse_date(value)
        return True
    except ValueError:
        return False


def add_days(date_str, days):
    return (parse_date(date_str) + timedelta(days=days)).isoformat()


def create_entity(table, fields):
    """Insert a new entity dict into the given store table with common fields."""
    STORE.seq += 1
    ts = now_iso()
    entity = dict(fields)
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = STORE.seq
    table[entity["id"]] = entity
    return entity


def touch(entity):
    """Mark an entity mutated: version +1 and updated_at refreshed (logical clock)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def public(entity):
    """Strip internal bookkeeping keys from an entity for serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_default(items):
    """Default list ordering: created_at ASC, insertion order as tie-break."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
