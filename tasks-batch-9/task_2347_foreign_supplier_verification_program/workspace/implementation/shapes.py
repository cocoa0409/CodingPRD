"""Request shape validation — PRD section 2.11 rung 3 (ERR_INVALID_REQUEST)."""
from datetime import datetime, timezone

from flask import request

from errors import fail

_MISSING = object()


def body():
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            fail("ERR_INVALID_REQUEST", "request body must be valid JSON")
    else:
        data = {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _get(b, name):
    return b.get(name, _MISSING)


def present(b, name):
    v = b.get(name, _MISSING)
    return v is not _MISSING and v is not None


def req_str(b, name, minlen=None, maxlen=None):
    v = _get(b, name)
    if v is _MISSING or v is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return _check_str(v, name, minlen, maxlen)


def opt_str(b, name, minlen=None, maxlen=None, default=None):
    v = _get(b, name)
    if v is _MISSING or v is None:
        return default
    return _check_str(v, name, minlen, maxlen)


def _check_str(v, name, minlen, maxlen):
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if minlen is not None and len(v) < minlen:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters" % (name, minlen))
    if maxlen is not None and len(v) > maxlen:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters" % (name, maxlen))
    return v


def req_int(b, name, lo=None, hi=None):
    v = _get(b, name)
    if v is _MISSING or v is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return _check_int(v, name, lo, hi)


def opt_int(b, name, lo=None, hi=None, default=None):
    v = _get(b, name)
    if v is _MISSING or v is None:
        return default
    return _check_int(v, name, lo, hi)


def _check_int(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if lo is not None and v < lo:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, lo))
    if hi is not None and v > hi:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, hi))
    return v


def req_bool(b, name):
    v = _get(b, name)
    if v is _MISSING or v is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return v


def opt_bool(b, name, default=None):
    v = _get(b, name)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return v


def opt_enum(b, name, allowed, default=None):
    v = opt_str(b, name)
    if v is None:
        return default
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return v


def parse_dt(value, name):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC datetime string" % name)
    raw = value.strip()
    if not raw:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC datetime string" % name)
    text = raw
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC datetime string" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, name):
    v = _get(b, name)
    if v is _MISSING or v is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return parse_dt(v, name)


def opt_dt(b, name, default=None):
    v = _get(b, name)
    if v is _MISSING or v is None:
        return default
    return parse_dt(v, name)


# ---------------------------------------------------------------- query params
def _query_int(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if lo is not None and value < lo:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, hi))
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (min 0)."""
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)


def query_dt(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return parse_dt(raw, name)
