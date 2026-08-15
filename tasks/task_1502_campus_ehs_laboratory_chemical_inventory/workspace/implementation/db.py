"""In-memory data store and logical clock.

The store starts EMPTY on every boot — no seeding of any kind. Every entity a
test needs is constructed through the declared API surface.
"""
import uuid
from datetime import datetime, timezone

# -----------------------------------------------------------------------------
# Entity stores: id -> record dict
# -----------------------------------------------------------------------------
labs = {}
workers = {}
containers = {}
accumulation_areas = {}
waste_pickup_requests = {}
inspections = {}
corrective_actions = {}
training_assignments = {}
incidents = {}
registrations = {}

# Monotonic creation counter for stable ordering tie-breaks (created_at ASC
# ordering; ties broken deterministically by insertion sequence).
_creation_seq = 0


def next_seq():
    global _creation_seq
    _creation_seq += 1
    return _creation_seq


def new_id():
    return str(uuid.uuid4())


# -----------------------------------------------------------------------------
# Logical clock (PRD §2.5): startup default 2026-08-01T00:00:00Z, never falls
# back to wall-clock. All time-dependent behavior evaluates against this.
# -----------------------------------------------------------------------------
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_now = _CLOCK_START


def now():
    return _logical_now


def set_now(value):
    global _logical_now
    _logical_now = value


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits.

    Internal comparisons run at 1-second granularity; stored/stamped values
    carry .000Z since all logical times are whole seconds.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string; returns aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
