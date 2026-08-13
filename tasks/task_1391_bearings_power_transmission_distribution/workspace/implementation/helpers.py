"""Shared low-level helpers: time, ids, rounding, field validation."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import err


# ---------------------------------------------------------------- time -----

def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return store.clock


def render_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="timestamp"):
    """Tolerant ISO 8601 parser; naive values treated as UTC."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_time(branch, at=None):
    """Branch-local time = logical clock shifted by timezone_offset_hours."""
    return (at or now()) + timedelta(hours=branch["timezone_offset_hours"])


# ---------------------------------------------------------------- ids ------

def new_id():
    return str(uuid.uuid4())


def touch(rec):
    """Version bump: +1 and updated_at refreshed to the logical-clock instant."""
    rec["version"] += 1
    rec["updated_at"] = now()


def stamp_new(rec):
    """Populate common system fields on a freshly created record."""
    rec["_seq"] = store.next_seq()
    rec["created_at"] = now()
    rec["updated_at"] = now()
    rec["version"] = 1
    return rec


# ------------------------------------------------------------- rounding ----

def rhu(value):
    """Round half-up to integer cents. Accepts int/Decimal."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Decimal from a JSON number without float artifacts."""
    return Decimal(str(value))


# ---------------------------------------------------------- field checks ---

def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a string")
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], str):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a string")
    return body[name]


def req_int(body, name, minimum=None):
    v = req_field(body, name)
    if not _is_int(v):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"{name} must be >= {minimum}")
    return v


def opt_int(body, name, default=None, minimum=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not _is_int(v):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"{name} must be >= {minimum}")
    return v


def req_num(body, name):
    v = req_field(body, name)
    if not (isinstance(v, (int, float)) and not isinstance(v, bool)):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a number")
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    if body[name] not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(allowed)}")
    return body[name]


def req_dt(body, name):
    return parse_dt(req_field(body, name), field=name)


FAMILIES = ("BEARING", "GEARBOX", "BELT", "CHAIN", "SEAL")
