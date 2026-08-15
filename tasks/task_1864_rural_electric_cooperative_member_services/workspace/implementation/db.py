"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock starts at exactly 2026-08-01T00:00:00Z per PRD §2.5.
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Module-level logical clock; mutated only by the _clock/set_current_utc endpoint.
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.cooperatives = {}
        self.members = {}
        self.service_locations = {}
        self.rate_schedules = {}
        self.meter_readings = {}
        self.invoices = {}
        self.capital_credit_allocations = {}
        self.capital_credit_allocation_lines = {}
        self.capital_credit_retirements = {}
        self.capital_credit_payouts = {}
        self.outage_reports = {}
        self.right_of_way_agreements = {}
        self.load_management_devices = {}
        self.service_orders = {}
        self.board_elections = {}
        self.ballots = {}
        self.escheat_ledger = []


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


def logical_now():
    """Current logical clock as a timezone-aware datetime."""
    return LOGICAL_CLOCK


def set_logical_clock(dt):
    global LOGICAL_CLOCK
    LOGICAL_CLOCK = dt


def iso_logical(dt):
    """Format a datetime as ISO 8601 UTC string."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    """Parse an ISO 8601 string into a timezone-aware datetime."""
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif "+" not in s and s.count("-") <= 2:
        s = s + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try common fallback formats
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                dt = datetime.strptime(str(s) if not s.endswith("Z") else s, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Cannot parse datetime: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity):
    """Refresh updated_at and bump version on a mutable entity."""
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity (id, created_at, updated_at, version)."""
    entity["id"] = new_id()
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def new_append_only(entity):
    """Stamp fields for append-only entities (MeterReading, Ballot): id + created_at only."""
    entity["id"] = new_id()
    entity["created_at"] = wall_now()
    entity["_seq"] = next_seq()
    return entity
