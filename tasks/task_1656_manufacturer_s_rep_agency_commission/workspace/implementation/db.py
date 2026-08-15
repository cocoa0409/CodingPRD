"""In-memory data store, logical clock, and shared helpers.

The store starts completely empty on every boot. The logical clock starts at
CLOCK_DEFAULT and only moves via POST /rep-agency/_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id). All empty at boot.
# ---------------------------------------------------------------------------
principals = {}
agreements = {}
rate_schedules = {}
reps = {}
customers = {}
registrations = {}
orders = {}
splits = {}
rmas = {}
entries = {}
statements = {}
sample_units = {}
checkouts = {}

# ---------------------------------------------------------------------------
# Logical clock state
# ---------------------------------------------------------------------------
_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}
_seq = {"n": 0}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# Timestamp helpers — ISO 8601 UTC with three fractional digits
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pub(obj):
    """Serialize a stored entity (dict) into its public wire form.

    - datetime -> ISO string
    - keys starting with '_' are internal and stripped
    """
    if isinstance(obj, datetime):
        return iso(obj)
    if isinstance(obj, dict):
        return {k: pub(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [pub(v) for v in obj]
    return obj


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def touch(entity):
    """Refresh updated_at and bump version on any entity mutation."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity):
    """Initialize common fields on a freshly created entity."""
    entity["id"] = new_id()
    entity["created_at"] = now()
    entity["updated_at"] = now()
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity
