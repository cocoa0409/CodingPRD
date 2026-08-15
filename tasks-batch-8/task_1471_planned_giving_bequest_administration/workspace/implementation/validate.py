"""Request body parsing + schema validation (ERR_INVALID_REQUEST, 400)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FM_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_dt(value):
    """Tolerant ISO 8601 parser: accepts 'YYYY-MM-DD' or full datetimes.
    Returns an aware UTC datetime, or None when unparseable."""
    if not isinstance(value, str):
        return None
    try:
        if _DATE_RE.match(value):
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        t = value
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def parse_funding_month(value):
    """'YYYY-MM' -> (year, month) or None."""
    if not isinstance(value, str) or not _FM_RE.match(value):
        return None
    y = int(value[:4])
    m = int(value[5:7])
    if m < 1 or m > 12:
        return None
    return (y, m)


def funding_month_start(value):
    y, m = parse_funding_month(value)
    return datetime(y, m, 1, tzinfo=timezone.utc)


def get_body():
    """Return the JSON object body ({} when no body was sent). 400 on malformed."""
    data = request.get_data(cache=True)
    if data is None or data.strip() == b"":
        return {}
    try:
        body = request.get_json(force=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed JSON body")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def validate_body(body, spec):
    """spec: {name: (kind, required, enum_or_None)}.
    kind in str/int/bool/datetime/funding_month/any.
    Unknown fields, missing required fields, malformed types and invalid enum
    members are rejected with ERR_INVALID_REQUEST (400)."""
    for key in body:
        if key not in spec:
            _bad("Unknown field: %s" % key)
    for name, (kind, required, enum) in spec.items():
        present = name in body and body[name] is not None
        if not present:
            if required:
                _bad("Missing required field: %s" % name)
            continue
        val = body[name]
        if kind == "str":
            if not isinstance(val, str):
                _bad("Field %s must be a string" % name)
        elif kind == "int":
            if not isinstance(val, int) or isinstance(val, bool):
                _bad("Field %s must be an integer" % name)
        elif kind == "bool":
            if not isinstance(val, bool):
                _bad("Field %s must be a boolean" % name)
        elif kind == "datetime":
            if parse_dt(val) is None:
                _bad("Field %s must be an ISO 8601 datetime" % name)
        elif kind == "funding_month":
            if parse_funding_month(val) is None:
                _bad("Field %s must be a YYYY-MM month" % name)
        elif kind == "any":
            pass
        if enum is not None and val not in enum:
            _bad("Field %s has an invalid value: %r" % (name, val))
