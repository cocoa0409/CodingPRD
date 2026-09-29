"""Request-shape validation (priority 4) and pagination parsing (PRD 2.3, 2.6)."""

from flask import request

from errors import ApiError
from util import parse_date, parse_dt

MISSING = object()

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def bad(field, why):
    raise ApiError("ERR_VALIDATION", "%s %s" % (field, why))


def get_body():
    """Parsed JSON object body; a missing body is treated as an empty object."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("body", "must be a JSON object")
    if not isinstance(payload, dict):
        bad("body", "must be a JSON object")
    return payload


def _present(body, name):
    return name in body and body[name] is not None


# --------------------------------------------------------------------------- #
# scalar field readers
# --------------------------------------------------------------------------- #


def req_str(body, name):
    if not _present(body, name):
        bad(name, "is required")
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad(name, "must be a non-empty string")
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad(name, "must be a non-empty string")
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        bad(name, "is required")
    return _check_int(name, body[name], minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return _check_int(name, body[name], minimum, maximum)


def _check_num(name, value, minimum, maximum, exclusive_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    if minimum is not None:
        if exclusive_min:
            if not value > minimum:
                bad(name, "must be > %s" % minimum)
        elif value < minimum:
            bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def req_num(body, name, minimum=None, maximum=None, exclusive_min=False):
    if not _present(body, name):
        bad(name, "is required")
    return _check_num(name, body[name], minimum, maximum, exclusive_min)


def opt_num(body, name, default=None, minimum=None, maximum=None, exclusive_min=False):
    if not _present(body, name):
        return default
    return _check_num(name, body[name], minimum, maximum, exclusive_min)


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def req_dt(body, name):
    if not _present(body, name):
        bad(name, "is required")
    parsed = parse_dt(body[name])
    if parsed is None:
        bad(name, "must be an ISO 8601 UTC datetime")
    return parsed


def req_date(body, name):
    if not _present(body, name):
        bad(name, "is required")
    parsed = parse_date(body[name])
    if parsed is None:
        bad(name, "must be a YYYY-MM-DD date")
    return parsed


def req_list(body, name):
    if not _present(body, name):
        bad(name, "is required")
    value = body[name]
    if not isinstance(value, list):
        bad(name, "must be an array")
    return value


def req_cents(body, name, minimum=0):
    """Cents-denominated fields are non-negative integers."""
    return req_int(body, name, minimum=minimum)


def forbid(body, name, why):
    if _present(body, name):
        bad(name, why)


# --------------------------------------------------------------------------- #
# query-string readers
# --------------------------------------------------------------------------- #


def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit", "must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad("limit", "must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset", "must be an integer")
        if offset < OFFSET_MIN:
            bad("offset", "must be >= %d" % OFFSET_MIN)
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed):
    value = q_str(name)
    if value is None:
        return None
    if value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def q_bool(name):
    value = q_str(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad(name, "must be true or false")
