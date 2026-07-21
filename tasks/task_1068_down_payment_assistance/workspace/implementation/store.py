"""In-memory data store, id/sequence/timestamp helpers, and the logical clock.

All state lives in module-level dicts. The store starts EMPTY on every boot;
nothing is seeded. start.sh re-invocation (fresh process) wipes everything.
"""
import uuid
from datetime import datetime, timezone, timedelta

# ----------------------------------------------------------------------------
# Collections keyed by id
# ----------------------------------------------------------------------------
programs = {}
income_limits = {}
applicants = {}
properties = {}
applications = {}
sessions = {}
enrollments = {}
certificates = {}
awards = {}
funding_sources = {}
allocations = {}
closings = {}
servicing = {}
sale_events = {}

COLLECTIONS = {
    "program": programs,
    "income_limit": income_limits,
    "applicant": applicants,
    "property": properties,
    "application": applications,
    "session": sessions,
    "enrollment": enrollments,
    "certificate": certificates,
    "award": awards,
    "funding_source": funding_sources,
    "allocation": allocations,
    "closing": closings,
    "servicing": servicing,
    "sale_event": sale_events,
}

# ----------------------------------------------------------------------------
# Monotonic insertion sequence (stable ordering for created_at-asc lists)
# ----------------------------------------------------------------------------
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ----------------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _CLOCK_DEFAULT


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# ----------------------------------------------------------------------------
# Timestamps
# ----------------------------------------------------------------------------
def now_wall():
    return datetime.now(timezone.utc)


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


# ----------------------------------------------------------------------------
# Common-field helpers
# ----------------------------------------------------------------------------
def new_record(kind, versioned=True):
    """Create a record dict pre-populated with common system fields."""
    wall = now_wall()
    rec = {
        "id": new_id(),
        "_kind": kind,
        "_seq": next_seq(),
        "created_at": format_ts(wall),
    }
    if versioned:
        rec["updated_at"] = format_ts(wall)
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: bump version and refresh updated_at."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = format_ts(now_wall())
