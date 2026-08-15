"""IDs, timestamps (wall clock for created/updated, logical clock for
workflow stamps), ISO8601 parsing, Decimal helpers, numeric serialization."""
import uuid
from datetime import datetime, timedelta, timezone

from db import store


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def wall_now():
    """created_at / updated_at: real UTC time at millisecond resolution,
    strictly monotonic so list ordering by created_at ASC is stable."""
    n = datetime.now(timezone.utc)
    n = n.replace(microsecond=(n.microsecond // 1000) * 1000)
    if store.last_ts is not None and n <= store.last_ts:
        n = store.last_ts + timedelta(milliseconds=1)
    store.last_ts = n
    return n


def logical_now():
    return store.logical_clock


def set_logical_clock(dt):
    store.logical_clock = dt


def fmt_ts(dt):
    """Common-field timestamp: ISO 8601 UTC, three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Logical-clock / user-supplied datetime: echo seconds precision when
    the value carries no sub-second component, else millisecond precision."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime.
    Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def num_out(v):
    """Serialize a numeric stored value: integral Decimals/floats as int,
    others as float (shortest round-trip repr)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    # Decimal or float
    try:
        integral = v == int(v)
    except Exception:
        integral = False
    if integral:
        return int(v)
    return float(v)
