"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence.

All entity timestamps (created_at, updated_at, transmitted_at, follow_up_due_at,
contacted_at, resolved_at, generated_at) are stamped from the server-maintained
logical clock (PRD §2.5): time-dependent rules such as the rejection follow-up
overdue computation compare the logical clock against those stamps, so they must
share one time base. The logical clock starts at exactly 2026-08-01T00:00:00Z and
never falls back to wall-clock time. The store starts empty on every boot.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# The logical clock (module-level; rebound only by routes/clock.py).
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.sites = {}
        self.volunteers = {}
        self.certifications = {}
        self.taxpayers = {}
        self.appointments = {}
        self.tax_returns = {}
        self.refund_allocations = {}
        self.efile_rejections = {}
        self.site_reports = {}
        self.financial_referrals = {}


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    """Strictly increasing wall-clock timestamp (response meta only)."""
    now = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _wall_last[0] = now
    return fmt_ts(now)


def logical_dt():
    """The current logical instant as an aware datetime."""
    return LOGICAL_CLOCK


def logical_ts():
    """The current logical instant as an ISO 8601 UTC string (3 fractional digits)."""
    return fmt_ts(LOGICAL_CLOCK)


def parse_iso(raw):
    """Parse an ISO 8601 string to an aware UTC datetime; None when invalid."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity (PRD §2.4)."""
    entity["updated_at"] = logical_ts()
    entity["version"] = entity.get("version", 0) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity (PRD §2.4)."""
    entity["id"] = new_id()
    entity["created_at"] = logical_ts()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity
