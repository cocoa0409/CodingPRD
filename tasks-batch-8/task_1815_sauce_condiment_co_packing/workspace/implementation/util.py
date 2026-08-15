"""Datetime parsing/formatting and request-shape validation helpers."""
import re
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST

UTC = timezone.utc


def parse_dt(value, name="datetime"):
    """Parse an ISO-8601 datetime (accepts date-only, 'Z', offsets, fractional
    seconds). Returns an aware UTC datetime. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not value.strip():
        raise err(ERR_INVALID_REQUEST, 400, f"malformed datetime: {value!r}")
    s = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)
        else:
            iso = s
            if iso.endswith(("Z", "z")):
                iso = iso[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
    except (ValueError, OverflowError):
        raise err(ERR_INVALID_REQUEST, 400, f"malformed datetime: {value!r}")
    return dt


def fmt_ts(dt):
    """System timestamp format (PRD §2.4): ISO 8601 UTC, three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Request-shape validation helpers (all raise ERR_INVALID_REQUEST, stage 5)
# ---------------------------------------------------------------------------

def body_json():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def req(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, 400, f"required field missing: {name}")
    return body[name]


def opt(body, name, default=None):
    v = body.get(name, default)
    return default if v is None else v


def as_str(v, name):
    if not isinstance(v, str) or not v:
        raise err(ERR_INVALID_REQUEST, 400, f"field must be a non-empty string: {name}")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, 400, f"field must be an integer: {name}")
    return v


def as_num(v, name):
    """A JSON number (int or float; bool excluded)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, 400, f"field must be a number: {name}")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, 400, f"field must be a boolean: {name}")
    return v


def check_enum(v, allowed, name):
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, 400, f"field {name} carries an undeclared value: {v!r}")
    return v


def as_dt(v, name):
    """Validate and parse an ISO-8601 datetime field."""
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, 400, f"field must be an ISO-8601 string: {name}")
    return parse_dt(v, name)
