"""In-memory data store, logical clock, and timestamp/ID helpers.

The store starts EMPTY on every boot. No seeding of any kind.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.properties = {}
        self.buildings = {}
        self.units = {}
        self.assets = {}
        self.templates = {}
        self.plans = {}
        self.batches = {}
        self.visits = {}
        self.evidence = {}
        self.deficiencies = {}
        self.work_orders = {}
        self.ledger = {}
        self.forecasts = {}
        self.audits = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def now():
    """Current logical clock (never wall-clock)."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def fmt_ts(dt):
    """System-generated timestamp: ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Logical-clock rendering: ISO 8601 UTC, seconds precision when whole."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_common_fields():
    """id/created_at/updated_at/version for primary (mutable) resources."""
    ts = fmt_ts(store.clock)
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_append_fields():
    """id/created_at only for append-only records."""
    return {
        "id": new_id(),
        "created_at": fmt_ts(store.clock),
        "_seq": next_seq(),
    }


def touch(rec):
    """Register a mutation: refresh updated_at and bump version."""
    rec["updated_at"] = fmt_ts(store.clock)
    rec["version"] = rec.get("version", 1) + 1


def parse_dt(value):
    """Parse an ISO 8601 date or datetime into an aware UTC datetime.

    Returns (datetime, is_date_only). Raises ValueError on garbage.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    try:
        if "T" not in s and " " not in s:
            d = datetime.strptime(s, "%Y-%m-%d")
            return d.replace(tzinfo=timezone.utc), True
        iso = s.replace("Z", "+00:00").replace("z", "+00:00")
        d = datetime.fromisoformat(iso)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc), False
    except (ValueError, OverflowError):
        raise ValueError("unparseable datetime: %r" % value)
