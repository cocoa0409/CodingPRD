"""Request-shape validation helpers (priority-0 checks -> ERR_INVALID_REQUEST)."""
import re
from datetime import datetime, date

from flask import request

import errors

_MMDD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DAYS_IN_MONTH = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _bad(msg):
    errors.raise_err(errors.INVALID_REQUEST, msg)


def get_body():
    """Parse the JSON request body; malformed JSON or non-object -> 400."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field):
    if not _present(body, field):
        _bad(f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        _bad(f"Field {field} must be a string")
    return v


def opt_str(body, field, default=None):
    if not _present(body, field):
        return default
    v = body[field]
    if not isinstance(v, str):
        _bad(f"Field {field} must be a string")
    return v


def req_int(body, field):
    if not _present(body, field):
        _bad(f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field {field} must be an integer")
    return v


def opt_int(body, field, default=None):
    if not _present(body, field):
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field {field} must be an integer")
    return v


def opt_bool(body, field, default=False):
    if not _present(body, field):
        return default
    v = body[field]
    if not isinstance(v, bool):
        _bad(f"Field {field} must be a boolean")
    return v


def req_enum(body, field, members):
    v = req_str(body, field)
    if v not in members:
        _bad(f"Field {field} must be one of {sorted(members)}")
    return v


def req_number(body, field):
    if not _present(body, field):
        _bad(f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(f"Field {field} must be a number")
    return v


def valid_mmdd(value):
    if not isinstance(value, str) or not _MMDD_RE.match(value):
        return False
    mm, dd = int(value[:2]), int(value[3:])
    return dd <= _DAYS_IN_MONTH[mm]


def req_mmdd(body, field):
    v = req_str(body, field)
    if not valid_mmdd(v):
        _bad(f"Field {field} must be a valid MM-DD string")
    return v


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime; returns aware datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def req_iso_datetime(body, field):
    v = req_str(body, field)
    dt = parse_iso_datetime(v)
    if dt is None:
        _bad(f"Field {field} must be a valid ISO 8601 datetime")
    from datetime import timezone
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def req_date(body, field):
    v = req_str(body, field)
    d = parse_date(v)
    if d is None:
        _bad(f"Field {field} must be a valid YYYY-MM-DD date")
    return d
