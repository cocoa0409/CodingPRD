"""In-memory data store. Fresh on every process boot -- never seeded/preloaded."""
import uuid
from datetime import datetime, timezone, timedelta

# Logical clock -- default 2026-07-01T00:00:00Z until a PlatformAdmin advances it.
DEFAULT_LOGICAL_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """Holds every entity table plus the server's logical clock."""

    def __init__(self):
        self.landlords = {}
        self.properties = {}
        self.renters = {}
        self.renter_enrollments = {}
        self.policies = {}
        self.invoices = {}
        self.claims = {}
        self.payouts = {}
        self.subrogation_cases = {}
        self.recovery_payments = {}
        self.state_compliance_rules = {}
        self.logical_clock = DEFAULT_LOGICAL_CLOCK


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Return the server's logical current time (NOT wall clock)."""
    return db.logical_clock


def set_logical_clock(dt):
    db.logical_clock = dt


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(value):
    """Parse an ISO 8601 timestamp (allowing trailing 'Z') into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months=1):
    """Add whole calendar months to a datetime (day-of-month preserved when possible)."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = dt.day
    # Clamp day to the last valid day of the target month.
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    day = min(day, last_day)
    return dt.replace(year=year, month=month, day=day)


def touch(entity):
    """Bump updated_at + version on a mutating write. StateComplianceRule is exempt."""
    entity["updated_at"] = fmt_ts(now())
    if "version" in entity:
        entity["version"] += 1
    return entity


def new_common_fields(has_version=True):
    ts = fmt_ts(now())
    fields = {"id": new_id(), "created_at": ts}
    if has_version:
        fields["updated_at"] = ts
        fields["version"] = 1
    return fields
