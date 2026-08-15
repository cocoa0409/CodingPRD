"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# The domain logical clock (module-level; rebound only by the clock endpoint).
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.parties = {}
        self.buildings = {}
        self.leases = {}
        self.demised_areas = {}
        self.transfer_requests = {}
        self.consent_reviews = {}
        self.consent_conditions = {}
        self.credit_reviews = {}
        self.sublease_agreements = {}
        self.recognition_agreements = {}
        self.settlements = {}
        self.restoration_obligations = {}


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def _fmt_iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    """Strictly increasing wall-clock ISO 8601 UTC timestamp, 3 fractional digits."""
    now = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _wall_last[0] = now
    return _fmt_iso(now)


def iso_logical(dt):
    """Format a logical-clock datetime as ISO 8601 UTC with 3 fractional digits."""
    return _fmt_iso(dt)


def parse_iso(s):
    """Parse an ISO 8601 string to a timezone-aware datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc) if s.tzinfo else s.replace(tzinfo=timezone.utc)
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
