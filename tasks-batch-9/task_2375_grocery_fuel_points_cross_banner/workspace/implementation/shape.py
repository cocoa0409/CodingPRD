"""Request-shape validation (PRD 2.10 step 3 -> ERR_INVALID_REQUEST) and pagination parsing."""
import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import response
from errors import ApiError, bad_request

_MISSING = object()


def body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except Exception:
        raise bad_request("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("request body must be a JSON object")
    return parsed


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _present(payload, name):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    return value


def req_str(payload, name, minlen=1, maxlen=None, pattern=None):
    value = _present(payload, name)
    if value is _MISSING:
        raise bad_request("'%s' is required" % name)
    return _check_str(value, name, minlen, maxlen, pattern)


def opt_str(payload, name, minlen=1, maxlen=None, pattern=None, default=None):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    return _check_str(value, name, minlen, maxlen, pattern)


def _check_str(value, name, minlen, maxlen, pattern):
    if not isinstance(value, str):
        raise bad_request("'%s' must be a string" % name)
    if minlen is not None and len(value) < minlen:
        raise bad_request("'%s' is too short" % name)
    if maxlen is not None and len(value) > maxlen:
        raise bad_request("'%s' is too long" % name)
    if pattern is not None and not re.match(pattern, value):
        raise bad_request("'%s' has an invalid format" % name)
    return value


def req_int(payload, name, lo=None, hi=None):
    value = _present(payload, name)
    if value is _MISSING:
        raise bad_request("'%s' is required" % name)
    return _check_int(value, name, lo, hi)


def opt_int(payload, name, default=None, lo=None, hi=None):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    return _check_int(value, name, lo, hi)


def _check_int(value, name, lo, hi):
    if not _is_int(value):
        raise bad_request("'%s' must be an integer" % name)
    if lo is not None and value < lo:
        raise bad_request("'%s' is below the accepted minimum" % name)
    if hi is not None and value > hi:
        raise bad_request("'%s' is above the accepted maximum" % name)
    return value


def req_enum(payload, name, allowed):
    value = req_str(payload, name, 1, None, None)
    if value not in allowed:
        raise bad_request("'%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("'%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def req_ts(payload, name):
    value = _present(payload, name)
    if value is _MISSING:
        raise bad_request("'%s' is required" % name)
    if not isinstance(value, str):
        raise bad_request("'%s' must be an ISO-8601 UTC timestamp" % name)
    parsed = clock.parse_ts(value)
    if parsed is None:
        raise bad_request("'%s' must be an ISO-8601 UTC timestamp" % name)
    return parsed


def req_decimal(payload, name, places=None):
    value = _present(payload, name)
    if value is _MISSING:
        raise bad_request("'%s' is required" % name)
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise bad_request("'%s' must be a number" % name)
    try:
        dec = Decimal(value) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError):
        raise bad_request("'%s' must be a number" % name)
    if not dec.is_finite():
        raise bad_request("'%s' must be a finite number" % name)
    if places is not None:
        quantised = clock.rhu(dec, places)
        if quantised != dec:
            raise bad_request("'%s' carries more than %d decimal places" % (name, places))
        dec = quantised
    return dec


def req_list(payload, name, minlen=1, maxlen=None):
    value = _present(payload, name)
    if value is _MISSING:
        raise bad_request("'%s' is required" % name)
    if not isinstance(value, list):
        raise bad_request("'%s' must be an array" % name)
    if minlen is not None and len(value) < minlen:
        raise bad_request("'%s' must contain at least %d element(s)" % (name, minlen))
    if maxlen is not None and len(value) > maxlen:
        raise bad_request("'%s' must contain at most %d element(s)" % (name, maxlen))
    return value


# ---------------------------------------------------------------- query params

def _arg_int(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw.strip()):
        raise bad_request("'%s' must be an integer" % name)
    value = int(raw.strip())
    if lo is not None and value < lo:
        raise bad_request("'%s' is below the accepted minimum" % name)
    if hi is not None and value > hi:
        raise bad_request("'%s' is above the accepted maximum" % name)
    return value


def pagination():
    limit = _arg_int("limit", response.PAGE_LIMIT_DEFAULT,
                     response.PAGE_LIMIT_MIN, response.PAGE_LIMIT_MAX)
    offset = _arg_int("offset", response.PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def arg_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad_request("'%s' must be one of %s" % (name, ", ".join(allowed)))
    return raw


def arg_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def arg_ts(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    parsed = clock.parse_ts(raw)
    if parsed is None:
        raise bad_request("'%s' must be an ISO-8601 UTC timestamp" % name)
    return parsed


def arg_int(name, lo=None, hi=None):
    return _arg_int(name, None, lo, hi)


def arg_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise bad_request("'%s' must be a boolean" % name)


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
