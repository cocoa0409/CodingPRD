"""In-memory data store, logical clock, identity and timestamp helpers.

Storage is process-local dicts only; the store starts empty on every boot.
The logical clock starts at exactly 2026-08-01T00:00:00Z and never falls
back to the wall clock.
"""
import itertools
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.seq = itertools.count(1)
        self.staff = {}
        self.batches = {}
        self.assets = {}
        self.proxies = {}
        self.grants = {}
        self.holds = {}
        self.policies = {}
        self.orders = {}
        self.requests = {}
        self.events = {}
        self.statements = {}
        self.jobs = {}
        self.tickets = {}
        self.workstations = {}


STORE = Store()


def now():
    """Current logical time (aware UTC datetime)."""
    return STORE.clock


def set_clock(dt):
    STORE.clock = dt


def new_id():
    return str(uuid.uuid4())


def stamp(rec):
    """Populate common fields on creation."""
    t = now()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next(STORE.seq)


def touch(rec):
    """Refresh updated_at and bump version on mutation (non-Asset entities)."""
    rec["updated_at"] = now()
    rec["version"] += 1


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a valid datetime string.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
