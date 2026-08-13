"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts completely empty on every boot — no seeding, no preloading.
The logical clock starts at exactly 2026-08-01T00:00:00Z (per PRD §2.8) and
never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock_now = _INITIAL_CLOCK


def clock_now():
    """Return the current logical-clock instant (timezone-aware UTC)."""
    return _clock_now


def clock_set(target):
    global _clock_now
    _clock_now = target


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits,
    e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


# ---------------------------------------------------------------------------
# Entity stores — empty dicts keyed by id. Nothing is seeded.
# ---------------------------------------------------------------------------

jurisdictions = {}
reviewers = {}
engagements = {}
cycles = {}
assignments = {}
comments = {}
responses = {}        # keyed by response id; each value has comment_id
deferred_submittals = {}
records = {}


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Refresh updated_at and bump version on a mutable resource."""
    entity["updated_at"] = clock_now()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity):
    """Initialize common system fields on a freshly created resource."""
    now = clock_now()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


# ---------------------------------------------------------------------------
# Serialization helpers (datetimes -> ISO strings)
# ---------------------------------------------------------------------------

_TS_FIELDS = (
    "created_at", "updated_at", "received_at", "due_at", "completed_at",
    "assigned_at", "ended_at", "sealed_at", "transmitted_at",
)


def serialize(entity):
    """Return a JSON-ready copy of an entity (datetimes rendered as strings)."""
    out = {}
    for k, v in entity.items():
        if k in _TS_FIELDS:
            out[k] = fmt_ts(v)
        elif isinstance(v, list):
            out[k] = [serialize(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out
