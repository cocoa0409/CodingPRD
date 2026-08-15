"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence.

The store starts empty on every boot — no entity is ever seeded at startup
(PRD benchmark contract: tests build all preconditions via the declared API).
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.5: the logical clock reads exactly 2026-08-01T00:00:00Z before any
# explicit setting and never falls back to wall-clock time.
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.trading_partners = {}
        self.partner_state_licenses = {}
        self.products = {}
        self.allocation_policies = {}
        self.serialized_cases = {}
        self.serialized_units = {}
        self.purchase_orders = {}
        self.order_lines = {}
        self.epcis_events = {}
        self.suspect_investigations = {}
        self.chargeback_claims = {}
        self.return_authorizations = {}


store = Store()


def logical_now():
    return LOGICAL_CLOCK


def set_logical_clock(dt):
    global LOGICAL_CLOCK
    LOGICAL_CLOCK = dt.astimezone(timezone.utc)
    return LOGICAL_CLOCK


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def _fmt(dt, millis):
    dt = dt.astimezone(timezone.utc)
    if millis:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_now():
    """Strictly increasing wall-clock ISO 8601 UTC timestamp, 3 fractional digits."""
    now = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _wall_last[0] = now
    return _fmt(now, millis=True)


def iso_logical(dt):
    """Format a logical-clock datetime as ISO 8601 UTC (Z-suffixed)."""
    return _fmt(dt, millis=False)


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Returns None when the value is not a parseable datetime string.
    """
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


def touch(entity):
    """Refresh updated_at and bump version on a mutable entity (PRD §2.4)."""
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity (PRD §2.4)."""
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def new_event_common(entity):
    """EpcisEvent is the sole common-fields exception: only id and created_at,
    both absent updated_at and version (PRD §2.4). created_at is the capture
    instant, i.e. the current logical clock, matching recorded_at."""
    entity["created_at"] = iso_logical(LOGICAL_CLOCK)
    entity["_seq"] = next_seq()
    return entity
