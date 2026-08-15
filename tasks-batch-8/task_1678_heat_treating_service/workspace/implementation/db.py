"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.5: at server startup the logical clock reads exactly 2026-08-01T00:00:00Z.
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_logical_clock = _CLOCK_START
_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.customers = {}
        self.recipes = {}
        self.furnaces = {}
        self.pyrometry_records = {}
        self.work_orders = {}
        self.load_batches = {}
        self.load_assignments = {}
        self.thermocouple_readings = {}
        self.inspection_tests = {}
        self.disposition_cases = {}
        self.liability_claims = {}
        self.audit_packages = {}


store = Store()


def clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def _fmt_wall(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    """Strictly increasing wall-clock ISO 8601 UTC timestamp, three fractional digits."""
    now = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _wall_last[0] = now
    return _fmt_wall(now)


def iso_logical(dt):
    """Format a logical-clock datetime as ISO 8601 UTC (fractional digits only when set)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime; None when invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity):
    """Refresh updated_at and bump version on a mutable (common-fields) entity."""
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp the common quartet plus insertion order on a freshly created entity."""
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def new_evidence(entity):
    """Append-only records (PyrometryRecord, LoadThermocoupleReading, InspectionTest):
    id + created_at only; updated_at and version are absent."""
    entity["created_at"] = wall_now()
    entity["_seq"] = next_seq()
    return entity
