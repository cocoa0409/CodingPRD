"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone, timedelta


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (for created_at/updated_at)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# ISO8601 helpers. All domain timestamps are stored as timezone-aware
# datetimes normalized to UTC; serialized with second precision + "Z"
# unless noted (created_at/updated_at use millisecond precision).
# ---------------------------------------------------------------------------

def parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    """Serialize datetime as ISO8601 UTC with second precision and Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK_START = "2026-05-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._current = parse_iso(_CLOCK_START)

    def get(self):
        return self._current

    def set(self, dt):
        self._current = dt

    def iso(self):
        return to_iso(self._current)


CLOCK = LogicalClock()


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_year(dt):
    """Add one calendar year (Mar 1 stays Mar 1; handles Feb 29 defensively)."""
    try:
        return dt.replace(year=dt.year + 1)
    except ValueError:
        # Feb 29 -> Feb 28 of next year
        return dt.replace(year=dt.year + 1, day=28)


def days_between(a, b):
    """Whole days from a to b (b - a), at day granularity."""
    delta = b - a
    return delta.days


# ---------------------------------------------------------------------------
# Stores: dict id -> record (plain dicts)
# ---------------------------------------------------------------------------

class DB:
    def __init__(self):
        self.landlords = {}
        self.tenants = {}
        self.fields = {}
        self.offerings = {}
        self.bids = {}
        self.leases = {}
        self.installments = {}
        self.settlements = {}
        self.expenses = {}
        self.compliance_records = {}
        self.improvements = {}
        self.notices = {}
        self.reports = {}


db = DB()


def new_common():
    """Common fields present on every entity."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(rec):
    """Refresh updated_at and bump version on mutation."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def touch_no_version(rec):
    rec["updated_at"] = now_iso()
