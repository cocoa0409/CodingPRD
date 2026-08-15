"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence.

The store starts empty on every boot — nothing is seeded at startup. The logical
clock (PRD §2.5) starts at exactly 2026-08-01T00:00:00Z and is only moved by
POST /api/_clock/set_current_utc; it never falls back to wall-clock time.
created_at/updated_at use a strictly monotonic wall clock (3 fractional digits)
so default list ordering and the generation created_at tie-break are stable.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Logical business clock (module-level; rebound only by routes/clock.py).
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]


class Store:
    """All ten entity tables. Instantiated empty; tests build all state via the API."""

    def __init__(self):
        self.programs = {}          # CallProgram
        self.physicians = {}        # Physician
        self.windows = {}           # UnavailabilityWindow
        self.slots = {}             # CallSlot
        self.assignments = {}       # CallAssignment
        self.swaps = {}             # SwapRequest
        self.gaps = {}              # CoverageGap
        self.requisitions = {}      # LocumRequisition
        self.cases = {}             # CredentialingCase
        self.pay_entries = {}       # PayEntry


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
    """Format a logical-clock datetime as ISO 8601 UTC (millis only when nonzero)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_logical():
    return LOGICAL_CLOCK


def set_logical(dt):
    global LOGICAL_CLOCK
    LOGICAL_CLOCK = dt.astimezone(timezone.utc)


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity (PRD §2.4)."""
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity."""
    entity["id"] = new_id()
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity
