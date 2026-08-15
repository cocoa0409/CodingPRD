"""In-memory data store and logical clock for the import buying-agent API.

The store starts completely empty on every boot; all entities are created via
the declared API surface. The logical clock defaults to 2026-08-01T00:00:00Z
and is driven exclusively through POST /sourcing/_clock/set_current_utc.
"""

import uuid
from datetime import datetime, timezone

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
INITIAL_CLOCK_STR = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.buyers = {}
        self.agents = {}
        self.factories = {}
        self.inspectors = {}
        self.audits = {}
        self.documents = {}
        self.sourcing_requests = {}
        self.samples = {}
        self.quotations = {}
        self.purchase_orders = {}
        self.milestones = {}
        self.inspections = {}
        self.shipments = {}
        self.claims = {}
        self.seq = 0
        self.clock = INITIAL_CLOCK
        self.clock_str = INITIAL_CLOCK_STR


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def format_dt(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Current logical-clock timestamp (three fractional digits)."""
    return format_dt(store.clock)


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date string to a date, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return dt.date()


def stamp_new(entity):
    """Attach common system fields to a freshly created entity."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_created_dt"] = store.clock
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Record a mutation: bump version and refresh updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def public(entity):
    """Serialize an entity, stripping internal underscore-prefixed fields."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
