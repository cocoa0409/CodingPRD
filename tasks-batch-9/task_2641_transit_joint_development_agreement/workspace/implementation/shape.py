"""Request shape validation (validations priority 3 -> ERR_INVALID_REQUEST 422).

Everything in here raises ERR_INVALID_REQUEST; it runs after auth/role and before
any existence check, per PRD 2.11.
"""

from decimal import Decimal

from flask import request

import store
from errors import fail

MISSING = object()


def body():
    """The JSON request body as a dict; a missing/invalid body reads as empty."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s" % (name, detail))


def _present(src, name, required, default):
    if name not in src or src[name] is None:
        if required:
            _bad(name, "is required")
        return MISSING if default is MISSING else default
    return src[name]


def as_str(src, name, required=True, default=None, min_len=None, max_len=None, non_empty=False):
    value = _present(src, name, required, default)
    if value is MISSING or (not required and name not in src) or value is None:
        return value if value is not MISSING else None
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if non_empty and value.strip() == "":
        _bad(name, "must be a non-empty string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def as_int(src, name, required=True, default=None, minimum=None, maximum=None):
    value = _present(src, name, required, default)
    if value is MISSING or value is None or (not required and name not in src):
        return value if value is not MISSING else None
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % maximum)
    return value


def as_num(src, name, required=True, default=None, minimum=None, maximum=None,
           exclusive_min=None):
    value = _present(src, name, required, default)
    if value is MISSING or value is None or (not required and name not in src):
        return value if value is not MISSING else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(name, "must be >= %s" % minimum)
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        _bad(name, "must be > %s" % exclusive_min)
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad(name, "must be <= %s" % maximum)
    return value


def as_bool(src, name, required=True, default=None):
    value = _present(src, name, required, default)
    if value is MISSING or value is None or (not required and name not in src):
        return value if value is not MISSING else None
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def as_enum(src, name, allowed, required=True, default=None):
    value = _present(src, name, required, default)
    if value is MISSING or value is None or (not required and name not in src):
        return value if value is not MISSING else None
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def as_date(src, name, required=True, default=None):
    """ISO 8601 calendar date YYYY-MM-DD."""
    value = _present(src, name, required, default)
    if value is MISSING or value is None or (not required and name not in src):
        return value if value is not MISSING else None
    if store.parse_date(value) is None:
        _bad(name, "must be an ISO 8601 calendar date YYYY-MM-DD")
    return value


def as_datetime(src, name, required=True, default=None):
    value = _present(src, name, required, default)
    if value is MISSING or value is None or (not required and name not in src):
        return value if value is not MISSING else None
    if store.parse_dt(value) is None:
        _bad(name, "must be an ISO 8601 datetime")
    return value


def line_items(src, name="line_items"):
    """Ordered array of { description: string, cost_cents: integer >= 0 }.

    Emptiness is NOT checked here: an empty array fails later at priority 60
    with ERR_EMPTY_LINE_ITEMS.
    """
    if name not in src or src[name] is None:
        _bad(name, "is required")
    value = src[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    cleaned = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            _bad("%s[%d]" % (name, idx), "must be an object")
        desc = item.get("description")
        if not isinstance(desc, str):
            _bad("%s[%d].description" % (name, idx), "must be a string")
        cost = item.get("cost_cents")
        if isinstance(cost, bool) or not isinstance(cost, int):
            _bad("%s[%d].cost_cents" % (name, idx), "must be an integer")
        if cost < 0:
            _bad("%s[%d].cost_cents" % (name, idx), "must be >= 0")
        cleaned.append({"description": desc, "cost_cents": cost})
    return cleaned


# ------------------------------------------------------------------ paging ---
def paging():
    """limit defaults to 10 (1..100 inclusive), offset defaults to 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if str(limit) != raw.strip():
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100 inclusive")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if str(offset) != raw.strip():
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
