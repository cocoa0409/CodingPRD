"""Request-shape validation helpers (validation order step 5 -> ERR_INVALID_REQUEST)."""

from datetime import date, datetime, timezone

from flask import request

from errors import fail

_MISSING = object()


def body():
    """Return the JSON body as a dict.  A non-object body is treated as empty so
    that body-FK existence (step 4) still runs before shape validation (step 5);
    the missing required fields then produce ERR_INVALID_REQUEST."""
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if isinstance(data, dict):
        return data
    return {}


def bad():
    fail("ERR_INVALID_REQUEST")


def _present(b, key):
    return key in b and b[key] is not None


def req_str(b, key):
    val = b.get(key, _MISSING)
    if val is _MISSING or not isinstance(val, str) or val.strip() == "":
        bad()
    return val


def opt_str(b, key, default=None):
    if not _present(b, key):
        return default
    val = b[key]
    if not isinstance(val, str):
        bad()
    return val


def _int_of(val, minimum, maximum):
    if isinstance(val, bool) or not isinstance(val, int):
        bad()
    if minimum is not None and val < minimum:
        bad()
    if maximum is not None and val > maximum:
        bad()
    return val


def req_int(b, key, minimum=None, maximum=None):
    if key not in b or b[key] is None:
        bad()
    return _int_of(b[key], minimum, maximum)


def opt_int(b, key, default=None, minimum=None, maximum=None):
    if not _present(b, key):
        return default
    return _int_of(b[key], minimum, maximum)


def req_enum(b, key, values):
    val = b.get(key, _MISSING)
    if val is _MISSING or not isinstance(val, str) or val not in values:
        bad()
    return val


def opt_enum(b, key, values, default=None):
    if not _present(b, key):
        return default
    val = b[key]
    if not isinstance(val, str) or val not in values:
        bad()
    return val


def opt_bool(b, key, default=None):
    if not _present(b, key):
        return default
    val = b[key]
    if not isinstance(val, bool):
        bad()
    return val


def parse_dt(val):
    if not isinstance(val, str) or not val.strip():
        return None
    text = val.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(b, key):
    if key not in b or b[key] is None:
        bad()
    parsed = parse_dt(b[key])
    if parsed is None:
        bad()
    return parsed


def parse_date(val):
    if not isinstance(val, str) or len(val.strip()) != 10:
        return None
    try:
        return date.fromisoformat(val.strip())
    except Exception:
        return None


def req_date(b, key):
    if key not in b or b[key] is None:
        bad()
    parsed = parse_date(b[key])
    if parsed is None:
        bad()
    return parsed


# ---------------------------------------------------------------- query params

def pagination():
    """limit default 20 (1..100); offset default 0 (>= 0).  Out of bounds or
    non-integer is a shape violation (PRD section 2.3)."""
    limit = 20
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad()
        if str(raw_limit).strip() != str(limit):
            bad()
        if limit < 1 or limit > 100:
            bad()
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad()
        if str(raw_offset).strip() != str(offset):
            bad()
        if offset < 0:
            bad()
    return limit, offset


def enum_filter(name, values):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        bad()
    return raw


def str_filter(name):
    return request.args.get(name)
