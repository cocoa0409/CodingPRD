"""In-memory store, the logical clock, and identity/audit-field helpers.

Storage is process-local Python dicts only.  Nothing is seeded at import time:
every entity is created through a declared endpoint.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from errors import ApiError

# ---------------------------------------------------------------------------
# collections (all empty at boot)
# ---------------------------------------------------------------------------

institutions = {}
giving_periods = {}
governance_authorizations = {}
pledge_campaigns = {}
pledges = {}
collateral_assets = {}
loan_applications = {}
loans = {}
draw_requests = {}
covenants = {}
workout_plans = {}

_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# logical clock — startup value is exactly 2026-08-01T00:00:00Z
# ---------------------------------------------------------------------------

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_START}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt.astimezone(timezone.utc)
    return _clock["now"]


# ---------------------------------------------------------------------------
# timestamps
# ---------------------------------------------------------------------------


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return datetime.now(timezone.utc)


def wall_now_iso():
    return iso_ms(wall_now())


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(start, end):
    """Whole days from start to end with any fractional day discarded."""
    return int((end - start).total_seconds() / 86400.0)


def plus_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# identity / audit fields
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_record():
    ts = wall_now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def _touched():
    marks = getattr(g, "_touched_ids", None)
    if marks is None:
        marks = set()
        g._touched_ids = marks
    return marks


def mark_created(entity):
    """A resource created in this request never advances past version 1."""
    _touched().add(entity["id"])


def touch(entity):
    """Refresh updated_at and advance version by at most 1 per request."""
    marks = _touched()
    entity["updated_at"] = wall_now_iso()
    if entity["id"] in marks:
        return entity
    marks.add(entity["id"])
    entity["version"] = entity.get("version", 1) + 1
    return entity


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------


def lookup(collection, value, error_id):
    """Resolve an identifier.

    A non-string / absent identifier is left to the request-shape rung of the
    ladder; a string that does not resolve raises the collection's 404.
    """
    if value is None or not isinstance(value, str):
        return None
    row = collection.get(value)
    if row is None:
        raise ApiError(error_id)
    return row


def children(collection, field, value):
    return [r for r in collection.values() if r.get(field) == value]


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
