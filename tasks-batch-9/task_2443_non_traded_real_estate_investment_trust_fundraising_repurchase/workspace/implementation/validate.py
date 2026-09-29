"""Schema validation — PRD §2.3 (pagination) and §2.9 level 3.

Every failure at this level is ERR_INVALID_REQUEST / HTTP 400.  Fields are
examined by the caller in the order the endpoint declares them (PRD §2.9:
"body fields are examined in the order in which the endpoint lists them").
"""

from flask import request

from errors import fail
from store import parse_date, parse_instant, parse_month

MISSING = object()


def json_body(silent=False):
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        if silent:
            return {}
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def present(body, name):
    return name in body and body[name] is not None


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def _raw(body, name, required):
    if not present(body, name):
        if required:
            _bad(name, "is required")
        return MISSING
    return body[name]


# --------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------

def integer(body, name, required=True, default=None, minimum=None, maximum=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d" % maximum)
    return value


def string(body, name, required=True, default=None, min_len=1, max_len=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def boolean(body, name, required=False, default=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def enum(body, name, allowed, required=True, default=None):
    value = _raw(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def date_field(body, name, required=True, default=None):
    """Returns (literal string, datetime.date) or (default, None)."""
    value = _raw(body, name, required)
    if value is MISSING:
        return default, None
    if not isinstance(value, str):
        _bad(name, "must be a YYYY-MM-DD calendar date")
    parsed = parse_date(value)
    if parsed is None:
        _bad(name, "must be a YYYY-MM-DD calendar date")
    return value, parsed


def month_field(body, name, required=True, default=None):
    """Returns (literal string, (year, month)) or (default, None)."""
    value = _raw(body, name, required)
    if value is MISSING:
        return default, None
    if not isinstance(value, str):
        _bad(name, "must be a YYYY-MM month")
    parsed = parse_month(value)
    if parsed is None:
        _bad(name, "must be a YYYY-MM month")
    return value, parsed


def instant_field(body, name, required=True, default=None):
    """Returns (literal string, datetime) or (default, None)."""
    value = _raw(body, name, required)
    if value is MISSING:
        return default, None
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 instant")
    parsed = parse_instant(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 instant")
    return value, parsed


def fk(body, name, required=True):
    value = _raw(body, name, required)
    if value is MISSING:
        return None
    if not isinstance(value, str) or not value:
        _bad(name, "must be a resource identifier string")
    return value


# --------------------------------------------------------------------------
# Query parameters
# --------------------------------------------------------------------------

def pagination():
    """PRD §2.3 — limit default 10 within 1..100, offset default 0 and never
    negative; anything else is a malformed request rather than a clamp."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if not _is_int_literal(raw):
            _bad("limit", "must be an integer between 1 and 100")
        limit = int(raw)
        if limit < 1 or limit > 100:
            _bad("limit", "must be an integer between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        if not _is_int_literal(raw):
            _bad("offset", "must be a non-negative integer")
        offset = int(raw)
        if offset < 0:
            _bad("offset", "must be a non-negative integer")
    return limit, offset


def _is_int_literal(raw):
    if raw is None:
        return False
    text = raw.strip()
    if text.startswith("-"):
        text = text[1:]
    return text.isdigit() and text != ""


def query_enum(name, allowed):
    """An unknown enum member in a filter is a malformed request (level 3)."""
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def query_string(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_date(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if parse_date(value) is None:
        _bad(name, "must be a YYYY-MM-DD calendar date")
    return value


def query_month(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if parse_month(value) is None:
        _bad(name, "must be a YYYY-MM month")
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
