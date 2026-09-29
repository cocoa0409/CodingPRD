"""Request-shape screening (PRD 2.11 band 4). Every failure here is
ERR_INVALID_REQUEST / HTTP 400."""

from decimal import Decimal

from flask import request

from errors import fail
from util import D, parse_iso, rhu


def body_of(request_obj=None):
    """Parse the JSON body. A body is optional for action endpoints with no input."""
    req = request_obj or request
    raw = req.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    data = req.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "%s %s" % (name, detail))


def _is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def num(body, name, required=True, default=None, gt=None, ge=None, lt=None, le=None, scale=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not _is_number(value):
        _bad(name, "must be a number")
    dec = D(value)
    if gt is not None and not dec > D(gt):
        _bad(name, "must be greater than %s" % gt)
    if ge is not None and dec < D(ge):
        _bad(name, "must be greater than or equal to %s" % ge)
    if lt is not None and not dec < D(lt):
        _bad(name, "must be less than %s" % lt)
    if le is not None and dec > D(le):
        _bad(name, "must be less than or equal to %s" % le)
    if scale is not None:
        dec = rhu(dec, scale)
    return dec


def integer(body, name, required=True, default=None, ge=None, le=None, gt=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be an integer")
    if isinstance(value, float):
        if value != int(value):
            _bad(name, "must be an integer")
        value = int(value)
    if gt is not None and not value > gt:
        _bad(name, "must be greater than %s" % gt)
    if ge is not None and value < ge:
        _bad(name, "must be greater than or equal to %s" % ge)
    if le is not None and value > le:
        _bad(name, "must be less than or equal to %s" % le)
    return value


def text(body, name, required=True, default=None, min_len=None, max_len=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def boolean(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def instant(body, name, required=True, default=None):
    """Returns (raw_string, datetime)."""
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default, None
    value = body[name]
    parsed = parse_iso(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 instant")
    return value, parsed


def one_of_number(body, name, allowed, required=True):
    """Numeric enumeration such as thickness_in in {0.375, 0.5, 0.625}."""
    value = num(body, name, required=required)
    if value is None:
        return None
    if not any(value == D(a) for a in allowed):
        _bad(name, "must be one of %s" % ", ".join(str(a) for a in allowed))
    return value


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
