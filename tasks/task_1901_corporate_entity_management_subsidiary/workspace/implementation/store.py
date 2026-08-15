"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding of any kind.
"""
import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK_START = "2026-08-01T00:00:00+00:00"
_clock = datetime.fromisoformat(_CLOCK_START)

# Monotonic insertion sequence for deterministic tie-breaking on created_at.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock = dt.astimezone(timezone.utc)


def today():
    """Calendar date of the logical clock in UTC."""
    return _clock.date()


def now_iso():
    """Logical clock as ISO 8601 UTC with three fractional digits."""
    return _clock.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (_clock.microsecond // 1000)


def clock_echo():
    """ISO 8601 UTC echo for clock endpoints (seconds precision when whole)."""
    if _clock.microsecond:
        return now_iso()
    return _clock.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id)
# ---------------------------------------------------------------------------
jurisdictions = {}
registered_agents = {}
officers = {}
entities = {}
agent_appointments = {}
resolutions = {}
officer_appointments = {}
filings = {}
qualifications = {}
grants = {}
certificates = {}
ownership_records = {}
compliance_events = {}


def new_record(common=True):
    """Base fields for a new resource."""
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": now_iso(),
    }
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at and version on mutation (common-fields resources)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1
