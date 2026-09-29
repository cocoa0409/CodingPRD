"""Request-shape validation (validation priority 30 -> ERR_INVALID_REQUEST)."""

from datetime import datetime, timezone

from flask import request

from db import iso
from errors import ApiError

_MISSING = object()


def bad(msg):
    return ApiError("ERR_INVALID_REQUEST", msg)


def get_body():
    """Parse the JSON body; a missing or non-object body behaves as {}."""
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad("request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_field(body, name):
    if not _present(body, name):
        raise bad("field '%s' is required" % name)
    return body[name]


# --------------------------------------------------------------------------
# scalars
# --------------------------------------------------------------------------

def _check_str(name, value, min_len=1, max_len=None):
    if not isinstance(value, str):
        raise bad("field '%s' must be a string" % name)
    if len(value) < min_len:
        raise bad("field '%s' must have at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("field '%s' must have at most %d characters" % (name, max_len))
    return value


def req_str(body, name, min_len=1, max_len=None):
    return _check_str(name, req_field(body, name), min_len, max_len)


def opt_str(body, name, default=None, min_len=1, max_len=None):
    if not _present(body, name):
        return default
    return _check_str(name, body[name], min_len, max_len)


def _check_int(name, value, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("field '%s' must be an integer" % name)
    if lo is not None and value < lo:
        raise bad("field '%s' must be >= %s" % (name, lo))
    if hi is not None and value > hi:
        raise bad("field '%s' must be <= %s" % (name, hi))
    return value


def req_int(body, name, lo=None, hi=None):
    return _check_int(name, req_field(body, name), lo, hi)


def opt_int(body, name, default=None, lo=None, hi=None):
    if not _present(body, name):
        return default
    return _check_int(name, body[name], lo, hi)


def _check_num(name, value, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("field '%s' must be a number" % name)
    value = float(value)
    if lo is not None and value < lo:
        raise bad("field '%s' must be >= %s" % (name, lo))
    if hi is not None and value > hi:
        raise bad("field '%s' must be <= %s" % (name, hi))
    return value


def req_num(body, name, lo=None, hi=None):
    return _check_num(name, req_field(body, name), lo, hi)


def opt_num(body, name, default=None, lo=None, hi=None):
    if not _present(body, name):
        return default
    return _check_num(name, body[name], lo, hi)


def _check_bool(name, value):
    if not isinstance(value, bool):
        raise bad("field '%s' must be a boolean" % name)
    return value


def req_bool(body, name):
    return _check_bool(name, req_field(body, name))


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return _check_bool(name, body[name])


def _check_enum(name, value, allowed):
    if not isinstance(value, str):
        raise bad("field '%s' must be a string" % name)
    if value not in allowed:
        raise bad("field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def req_enum(body, name, allowed):
    return _check_enum(name, req_field(body, name), allowed)


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return _check_enum(name, body[name], allowed)


def _check_id(name, value):
    return _check_str(name, value, 1, None)


def req_id(body, name):
    return _check_id(name, req_field(body, name))


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    return _check_id(name, body[name])


# --------------------------------------------------------------------------
# dates and datetimes
# --------------------------------------------------------------------------

def parse_date(name, value):
    if not isinstance(value, str):
        raise bad("field '%s' must be a YYYY-MM-DD date" % name)
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        raise bad("field '%s' must be a YYYY-MM-DD date" % name)
    return d


def req_date(body, name):
    return parse_date(name, req_field(body, name))


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    return parse_date(name, body[name])


def parse_datetime(name, value):
    """Accept ISO 8601 UTC; return an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise bad("field '%s' must be an ISO 8601 UTC datetime" % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        raise bad("field '%s' must be an ISO 8601 UTC datetime" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def req_datetime(body, name):
    return parse_datetime(name, req_field(body, name))


def opt_datetime(body, name, default=None):
    if not _present(body, name):
        return default
    return parse_datetime(name, body[name])


def dt_out(dt):
    """Canonical ISO 8601 UTC rendering with exactly three fractional digits."""
    return iso(dt)


def date_out(d):
    return d.isoformat() if d is not None else None


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MAX_LIMIT = 100


def _query_int(name, raw, lo, hi):
    text = raw.strip()
    if text == "":
        raise bad("query parameter '%s' must be an integer" % name)
    try:
        value = int(text)
    except Exception:
        raise bad("query parameter '%s' must be an integer" % name)
    if lo is not None and value < lo:
        raise bad("query parameter '%s' must be >= %s" % (name, lo))
    if hi is not None and value > hi:
        raise bad("query parameter '%s' must be <= %s" % (name, hi))
    return value


def pagination():
    limit = DEFAULT_LIMIT
    offset = 0
    raw = request.args.get("limit")
    if raw is not None:
        limit = _query_int("limit", raw, 1, MAX_LIMIT)
    raw = request.args.get("offset")
    if raw is not None:
        offset = _query_int("offset", raw, 0, None)
    return limit, offset


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise bad("query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return raw


def q_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw == "":
        raise bad("query parameter '%s' must not be empty" % name)
    return raw


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise bad("query parameter '%s' must be a boolean" % name)


def q_date(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return parse_date(name, raw)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
