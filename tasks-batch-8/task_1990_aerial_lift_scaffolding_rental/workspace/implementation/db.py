"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# The branch logical clock (module-level; rebound only by routes/clock.py).
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.customers = {}
        self.classes = {}
        self.units = {}
        self.contracts = {}
        self.lines = {}
        self.trips = {}
        self.inspections = {}
        self.claims = {}
        self.training = {}


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def _fmt_wall(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    """Strictly increasing wall-clock ISO 8601 UTC timestamp, 3 fractional digits."""
    now = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _wall_last[0] = now
    return _fmt_wall(now)


def iso_logical(dt):
    """Format a logical-clock datetime as ISO 8601 UTC (3 fractional digits when set)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def logical_stamp():
    return iso_logical(LOGICAL_CLOCK)


def logical_date():
    return LOGICAL_CLOCK.astimezone(timezone.utc).date()


def parse_datetime(raw):
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(raw):
    return datetime.strptime(raw, "%Y-%m-%d").date()


def is_valid_date_string(raw):
    if not isinstance(raw, str) or len(raw) != 10:
        return False
    if raw[4] != "-" or raw[7] != "-":
        return False
    try:
        parse_date(raw)
    except ValueError:
        return False
    return True


def is_valid_datetime_string(raw):
    if not isinstance(raw, str):
        return False
    try:
        parse_datetime(raw)
    except ValueError:
        return False
    return True


def touch(entity):
    """Refresh updated_at and bump version on a mutable entity."""
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity."""
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity
