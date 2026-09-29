"""Request-body shape helpers — ladder step 5 (ERR_INVALID_REQUEST, HTTP 400)."""

from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import fail

BAD = "ERR_INVALID_REQUEST"


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(BAD, "Request body must be a JSON object")
    return data


def _present(data, name):
    return name in data and data[name] is not None


# ---------------------------------------------------------------------------
# scalars
# ---------------------------------------------------------------------------
def req_str(data, name, allow_empty=True):
    if not _present(data, name):
        fail(BAD, "%s is required" % name)
    value = data[name]
    if not isinstance(value, str):
        fail(BAD, "%s must be a string" % name)
    if not allow_empty and not value.strip():
        fail(BAD, "%s must be non-empty" % name)
    return value


def opt_str(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        fail(BAD, "%s must be a string" % name)
    return value


def _as_int(value, name):
    if isinstance(value, bool):
        fail(BAD, "%s must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    fail(BAD, "%s must be an integer" % name)


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        fail(BAD, "%s is required" % name)
    value = _as_int(data[name], name)
    _range(value, name, minimum, maximum)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    value = _as_int(data[name], name)
    _range(value, name, minimum, maximum)
    return value


def _range(value, name, minimum, maximum):
    if minimum is not None and value < minimum:
        fail(BAD, "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail(BAD, "%s must be <= %s" % (name, maximum))


def _as_dec(value, name):
    if isinstance(value, bool):
        fail(BAD, "%s must be a number" % name)
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            fail(BAD, "%s must be a number" % name)
    fail(BAD, "%s must be a number" % name)


def req_num(data, name, minimum=None, maximum=None, exclusive_min=None):
    if not _present(data, name):
        fail(BAD, "%s is required" % name)
    value = _as_dec(data[name], name)
    if exclusive_min is not None and value <= Decimal(str(exclusive_min)):
        fail(BAD, "%s must be > %s" % (name, exclusive_min))
    if minimum is not None and value < Decimal(str(minimum)):
        fail(BAD, "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        fail(BAD, "%s must be <= %s" % (name, maximum))
    return value


def opt_num(data, name, default=None, minimum=None, exclusive_min=None):
    if not _present(data, name):
        return default
    value = _as_dec(data[name], name)
    if exclusive_min is not None and value <= Decimal(str(exclusive_min)):
        fail(BAD, "%s must be > %s" % (name, exclusive_min))
    if minimum is not None and value < Decimal(str(minimum)):
        fail(BAD, "%s must be >= %s" % (name, minimum))
    return value


def req_bool(data, name, default=None):
    if not _present(data, name):
        if default is None:
            fail(BAD, "%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail(BAD, "%s must be a boolean" % name)
    return value


def opt_bool(data, name, default=False):
    return req_bool(data, name, default=default)


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        fail(BAD, "%s must be one of %s" % (name, sorted(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail(BAD, "%s must be one of %s" % (name, sorted(allowed)))
    return value


def req_ts(data, name):
    if not _present(data, name):
        fail(BAD, "%s is required" % name)
    value = data[name]
    parsed = store.parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        fail(BAD, "%s must be an ISO 8601 instant" % name)
    return parsed


def opt_fk(data, name):
    """A body FK reference: must be a string when supplied."""
    if not _present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        fail(BAD, "%s must be a string identifier" % name)
    return value


def req_fk(data, name):
    value = opt_fk(data, name)
    if value is None:
        fail(BAD, "%s is required" % name)
    return value


# ---------------------------------------------------------------------------
# pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail(BAD, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail(BAD, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail(BAD, "offset must be an integer")
        if offset < 0:
            fail(BAD, "offset must be >= 0")
    return limit, offset


def qparam(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
