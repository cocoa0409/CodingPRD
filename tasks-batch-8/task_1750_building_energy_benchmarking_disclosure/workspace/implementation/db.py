"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence.

The store starts empty on every boot — no entity seeding at startup. Every
entity is constructed through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD section 2.5: before any set_current_utc call the logical clock reads
# exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.owners = {}
        self.verifiers = {}
        self.cycles = {}
        self.buildings = {}
        self.tenant_units = {}
        self.consent_grants = {}
        self.utility_accounts = {}
        self.usage_records = {}
        self.reports = {}
        self.verification_records = {}
        self.anomaly_flags = {}
        self.fines = {}
        self.exemption_requests = {}
        self.publications = {}


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
    """Format a logical-clock datetime as ISO 8601 UTC."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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
