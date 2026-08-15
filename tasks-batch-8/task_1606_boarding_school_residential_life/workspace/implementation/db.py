"""In-memory data store, logical clock, and primitive helpers.

The store starts completely empty on every boot.  No seeding of any kind.
The logical clock starts at exactly 2026-08-01T00:00:00Z and only moves when
POST /reslife/_clock/set_current_utc advances it.
"""

import random
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

INITIAL_CLOCK_ISO = "2026-08-01T00:00:00Z"

STORE = {
    "terms": {},
    "dorms": {},
    "rooms": {},
    "parents": {},
    "guardians": {},
    "staff": {},
    "students": {},
    "dorm_assignments": {},
    "leave_requests": {},
    "sign_events": {},
    "duty_shifts": {},
    "night_checks": {},
    "medication_orders": {},
    "medication_administrations": {},
    "discipline_cases": {},
    "break_periods": {},
    "break_housing_requests": {},
    "storage_units": {},
    "storage_reservations": {},
}

# Monotonic creation sequence; stable tie-breaker for created_at sorting.
SEQ = [0]

# The logical clock (timezone-aware UTC datetime).
CLOCK = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    SEQ[0] += 1
    return SEQ[0]


def now():
    return CLOCK[0]


def set_clock(dt):
    CLOCK[0] = dt


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (
        dt.microsecond // 1000
    )


def new_request_id():
    return "req_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
    )


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z") or s.endswith("z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD) into a date, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time_hhmm(value):
    """Parse an HH:MM 24h string into a (hour, minute) tuple, or None."""
    if not isinstance(value, str):
        return None
    try:
        t = datetime.strptime(value.strip(), "%H:%M")
        return (t.hour, t.minute)
    except ValueError:
        return None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_bool(v):
    return isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def touch(entity, seq=True):
    """Refresh updated_at; bumps are handled separately via bump()."""
    entity["updated_at"] = now()
    if seq:
        entity["_seq"] = next_seq()


def bump(entity):
    """Material mutation: version += 1 and updated_at refreshed."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now()
    entity["_seq"] = next_seq()
