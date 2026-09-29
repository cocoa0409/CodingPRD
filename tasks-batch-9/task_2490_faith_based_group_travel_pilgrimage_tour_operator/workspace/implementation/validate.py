"""Request-shape validation helpers (ladder stages 5 and 6)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import err

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)

MISSING = object()


def body_of(required=True):
    """Parse the JSON body.  A body that is present but not a JSON object is
    ERR_INVALID_REQUEST; an absent body behaves like an empty object so that
    endpoints without declared inputs accept no payload at all."""
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        err("ERR_INVALID_REQUEST", "Body must be valid JSON.")
    if not isinstance(parsed, dict):
        err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return parsed


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, min_len=1, max_len=None):
    if not _present(body, key):
        err("ERR_INVALID_REQUEST", "%s is required." % key)
    return _check_str(body[key], key, min_len, max_len)


def opt_str(body, key, min_len=1, max_len=None, default=None, allow_null=True):
    if key not in body:
        return default
    if body[key] is None:
        if allow_null:
            return None
        err("ERR_INVALID_REQUEST", "%s may not be null." % key)
    return _check_str(body[key], key, min_len, max_len)


def _check_str(value, key, min_len, max_len):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "%s must be a string." % key)
    if min_len is not None and len(value) < min_len:
        err("ERR_INVALID_REQUEST", "%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        err("ERR_INVALID_REQUEST", "%s must be at most %d characters." % (key, max_len))
    return value


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        err("ERR_INVALID_REQUEST", "%s is required." % key)
    return _check_int(body[key], key, minimum, maximum)


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if key not in body or body[key] is None:
        return default
    return _check_int(body[key], key, minimum, maximum)


def _check_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", "%s must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        err("ERR_INVALID_REQUEST", "%s must be <= %d." % (key, maximum))
    return value


def req_bool(body, key):
    if not _present(body, key):
        err("ERR_INVALID_REQUEST", "%s is required." % key)
    if not isinstance(body[key], bool):
        err("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return body[key]


def opt_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    if not isinstance(body[key], bool):
        err("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return body[key]


def req_enum(body, key, allowed):
    value = req_str(body, key, 1, None)
    if value not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return default
    value = _check_str(body[key], key, 1, None)
    if value not in allowed:
        err("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def parse_date_str(value, key):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        err("ERR_INVALID_REQUEST", "%s must be an ISO-8601 calendar date (YYYY-MM-DD)." % key)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        err("ERR_INVALID_REQUEST", "%s is not a valid calendar date." % key)


def req_date(body, key):
    if not _present(body, key):
        err("ERR_INVALID_REQUEST", "%s is required." % key)
    return parse_date_str(body[key], key)


def opt_date(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return parse_date_str(body[key], key)


def parse_datetime_str(value, key):
    """RFC 3339 instant.  An offset designator is required; the value is
    normalised to UTC."""
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "%s must be an RFC3339 UTC timestamp." % key)
    m = _DT_RE.match(value.strip())
    if not m:
        err("ERR_INVALID_REQUEST", "%s must be an RFC3339 UTC timestamp." % key)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        err("ERR_INVALID_REQUEST", "%s is not a valid timestamp." % key)
    if offset in ("Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    delta_minutes = sign * (int(offset[1:3]) * 60 + int(offset[4:6]))
    from datetime import timedelta

    return (naive - timedelta(minutes=delta_minutes)).replace(tzinfo=timezone.utc)


def req_datetime(body, key):
    if not _present(body, key):
        err("ERR_INVALID_REQUEST", "%s is required." % key)
    return parse_datetime_str(body[key], key)


def opt_datetime(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return parse_datetime_str(body[key], key)


def req_id(body, key):
    """A foreign-key reference in a body: must be a non-empty string."""
    if not _present(body, key):
        err("ERR_INVALID_REQUEST", "%s is required." % key)
    if not isinstance(body[key], str) or body[key] == "":
        err("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return body[key]


def opt_id(body, key):
    if key not in body or body[key] is None:
        return None
    if not isinstance(body[key], str) or body[key] == "":
        err("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return body[key]


def apply_filters(rows, mapping):
    """Conjunctive equality filters: query-param name -> row field name."""
    for param, field in mapping.items():
        if param in request.args:
            wanted = request.args.get(param)
            rows = [r for r in rows if r.get(field) == wanted]
    return rows


def pagination():
    """limit default 10 (1..100), offset default 0 (>= 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.match(r"^[+-]?\d+$", raw.strip()):
            err("ERR_INVALID_PAGINATION", "limit must be an integer.")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            err("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.match(r"^[+-]?\d+$", raw.strip()):
            err("ERR_INVALID_PAGINATION", "offset must be an integer.")
        offset = int(raw.strip())
        if offset < 0:
            err("ERR_INVALID_PAGINATION", "offset must be >= 0.")
    return limit, offset
