"""Request-body / query-string shape validation (rejection ladder rank 3)."""

from flask import request

from db import parse_iso
from errors import fail

_MISSING = object()


def bad(message):
    fail("ERR_INVALID_REQUEST", message)


def get_body():
    """Parse the JSON body.  An absent body is treated as an empty object so
    that endpoints with no required inputs accept a bodyless POST."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        bad("Request body must be a JSON object")
    return parsed


# ---------------------------------------------------------------- scalars
def _present(body, name):
    if name not in body or body[name] is None:
        return False
    return True


def req_str(body, name, max_len=None, allow_blank=False):
    if not _present(body, name):
        bad("%s is required" % name)
    return _str(body[name], name, max_len, allow_blank)


def opt_str(body, name, default=None, max_len=None, allow_blank=True):
    if not _present(body, name):
        return default
    return _str(body[name], name, max_len, allow_blank)


def _str(value, name, max_len, allow_blank):
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if not allow_blank and value.strip() == "":
        bad("%s must be non-empty" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        bad("%s is required" % name)
    return _int(body[name], name, minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return _int(body[name], name, minimum, maximum)


def _int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return value


def req_num(body, name, minimum=None, maximum=None, exclusive_min=None):
    if not _present(body, name):
        bad("%s is required" % name)
    return _num(body[name], name, minimum, maximum, exclusive_min)


def opt_num(body, name, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not _present(body, name):
        return default
    return _num(body[name], name, minimum, maximum, exclusive_min)


def _num(value, name, minimum, maximum, exclusive_min):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (name, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        bad("%s must be > %s" % (name, exclusive_min))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return value


def req_bool(body, name):
    if not _present(body, name):
        bad("%s is required" % name)
    return _bool(body[name], name)


def opt_bool(body, name, default=False):
    if not _present(body, name):
        return default
    return _bool(body[name], name)


def _bool(value, name):
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def req_enum(body, name, choices):
    if not _present(body, name):
        bad("%s is required" % name)
    return _enum(body[name], name, choices)


def opt_enum(body, name, choices, default=None):
    if not _present(body, name):
        return default
    return _enum(body[name], name, choices)


def _enum(value, name, choices):
    if not isinstance(value, str) or value not in choices:
        bad("%s must be one of %s" % (name, ", ".join(choices)))
    return value


def req_dt(body, name):
    if not _present(body, name):
        bad("%s is required" % name)
    return _dt(body[name], name)


def opt_dt(body, name, default=None):
    if not _present(body, name):
        return default
    return _dt(body[name], name)


def _dt(value, name):
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        bad("%s must be an ISO 8601 timestamp" % name)


# ---------------------------------------------------------------- pagination
def pagination():
    """limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be >= 0")
    return limit, offset


def page(records, limit, offset):
    return records[offset : offset + limit]
