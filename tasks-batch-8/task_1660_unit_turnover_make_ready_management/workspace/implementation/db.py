"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence.

The store starts empty on every boot — no seeding anywhere (per the benchmark
contract every precondition is built through the declared API surface).
"""
import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone

# PRD §2.5: startup value of the logical clock; never falls back to wall-clock.
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.properties = {}
        self.units = {}
        self.turns = {}
        self.scope_items = {}
        self.vendors = {}
        self.assignments = {}
        self.inspections = {}
        self.decisions = {}
        self.commitments = {}


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
    """The current logical-clock instant (an aware UTC datetime)."""
    return LOGICAL_CLOCK


def logical_date():
    """The current logical-clock calendar date (PRD stamps whole ISO dates)."""
    return LOGICAL_CLOCK.date()


def set_logical_clock(dt):
    global LOGICAL_CLOCK
    LOGICAL_CLOCK = dt


def touch(entity):
    """Refresh updated_at and bump version on a mutable entity."""
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def refresh(entity):
    """Refresh updated_at without bumping version (derived-field reconciliation)."""
    entity["updated_at"] = wall_now()


def new_common(entity):
    """Stamp common system fields on a freshly created entity (PRD §2.4)."""
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_date_string(value):
    """True iff value is a strict YYYY-MM-DD string naming a real calendar date."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_date(value):
    return date.fromisoformat(value)
