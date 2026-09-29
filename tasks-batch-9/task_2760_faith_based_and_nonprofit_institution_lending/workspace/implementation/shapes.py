"""Request-shape validation — ladder rung 15, ERR_INVALID_REQUEST (422)."""

from decimal import Decimal

from flask import request

import store
from errors import ApiError

MISSING = object()


def bad(field, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(b, name):
    return name in b and b[name] is not None


def req_str(b, name):
    if not _present(b, name):
        bad(name, "is required")
    value = b[name]
    if not isinstance(value, str) or not value.strip():
        bad(name, "must be a non-empty string")
    return value


def opt_str(b, name, default=None):
    if not _present(b, name):
        return default
    value = b[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    return value


def req_int(b, name, minimum=None, exclusive_minimum=None, maximum=None):
    if not _present(b, name):
        bad(name, "is required")
    value = b[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        bad(name, "must be > %s" % exclusive_minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def opt_int(b, name, default=None, minimum=None, exclusive_minimum=None,
            maximum=None):
    if not _present(b, name):
        return default
    return req_int(b, name, minimum, exclusive_minimum, maximum)


def req_enum(b, name, choices):
    value = req_str(b, name)
    if value not in choices:
        bad(name, "must be one of %s" % ", ".join(sorted(choices)))
    return value


def opt_enum(b, name, choices, default=None):
    if not _present(b, name):
        return default
    return req_enum(b, name, choices)


def req_bool(b, name):
    if not _present(b, name):
        bad(name, "is required")
    value = b[name]
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def opt_bool(b, name, default=None):
    if not _present(b, name):
        return default
    return req_bool(b, name)


def req_dt(b, name):
    raw = req_str(b, name)
    parsed = store.parse_dt(raw)
    if parsed is None:
        bad(name, "must be an ISO 8601 UTC instant")
    return raw, parsed


def opt_dt(b, name):
    if not _present(b, name):
        return None, None
    return req_dt(b, name)


def req_ratio(b, name, gt=None, ge=None, le=None, places=4):
    if not _present(b, name):
        bad(name, "is required")
    value = b[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    dec = Decimal(str(value))
    if gt is not None and dec <= Decimal(str(gt)):
        bad(name, "must be > %s" % gt)
    if ge is not None and dec < Decimal(str(ge)):
        bad(name, "must be >= %s" % ge)
    if le is not None and dec > Decimal(str(le)):
        bad(name, "must be <= %s" % le)
    from calc import rhu
    return rhu(dec, places)


def req_id_field(b, name):
    """A required foreign-key string field, checked after existence resolution."""
    if not _present(b, name):
        bad(name, "is required")
    if not isinstance(b[name], str) or not b[name].strip():
        bad(name, "must be a non-empty string")
    return b[name]


def opt_id_field(b, name):
    if not _present(b, name):
        return None
    if not isinstance(b[name], str) or not b[name].strip():
        bad(name, "must be a non-empty string")
    return b[name]
