"""In-memory data store, logical clock, id/timestamp helpers.

The store starts empty on every boot. No seeding of any kind.
All server-side time comes from the logical clock (never the wall clock);
default before any clock-set call is 2026-08-01T00:00:00Z.
"""

import uuid
from datetime import datetime, timezone

from errors import ApiError, ERR_INVALID_REQUEST

STORE = {
    "carriers": {},
    "lanes": {},
    "assignments": {},
    "shipments": {},
    "claims": {},
    "documents": {},
    "assessments": {},
    "salvage": {},
    "appeals": {},
    "settlements": {},
    "subrogation": {},
    "reserves": {},
    "events": {},
    "calendar": {},
}

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}
_seq = {"n": 0}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def now_iso():
    return iso(_clock["now"])


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field_name):
    """Parse an ISO 8601 datetime string; naive values are treated as UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST,
                       f"Field '{field_name}' must be an ISO 8601 datetime string", 400)
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST,
                       f"Field '{field_name}' is not a valid ISO 8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
