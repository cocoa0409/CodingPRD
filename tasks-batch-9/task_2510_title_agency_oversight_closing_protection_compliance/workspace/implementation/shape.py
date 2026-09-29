"""Tier 3 of the precedence ladder: request shape, plus pagination parsing.

Unknown fields are ignored, and any computed or system-owned field a client
tries to supply is ignored rather than rejected (PRD 2.11 tier 3).
"""

import re

from flask import request

import db
from errors import ApiError

_INT_RE = re.compile(r"^[+-]?[0-9]+$")


def bad(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict; a missing body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


# ---------------------------------------------------------------------------
# scalar validators
# ---------------------------------------------------------------------------
def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name):
    if not _present(payload, name):
        raise bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        raise bad("%s must be a string." % name)
    return value


def opt_str(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise bad("%s must be a string." % name)
    return value


def _as_int(name, value, minimum=None, exclusive_minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("%s must be at least %d." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise bad("%s must be greater than %d." % (name, exclusive_minimum))
    return value


def req_int(payload, name, minimum=None, exclusive_minimum=None):
    if not _present(payload, name):
        raise bad("%s is required." % name)
    return _as_int(name, payload[name], minimum, exclusive_minimum)


def opt_int(payload, name, default=None, minimum=None, exclusive_minimum=None):
    if not _present(payload, name):
        return default
    return _as_int(name, payload[name], minimum, exclusive_minimum)


def req_cents(payload, name):
    """A `_cents` integer, non-negative per tier 3."""
    return req_int(payload, name, minimum=0)


def req_positive_cents(payload, name):
    return req_int(payload, name, exclusive_minimum=0)


def req_bool(payload, name):
    if not _present(payload, name):
        raise bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, bool):
        raise bad("%s must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise bad("%s must be a boolean." % name)
    return value


def req_enum(payload, name, domain):
    value = req_str(payload, name)
    if value not in domain:
        raise bad("%s must be one of %s." % (name, ", ".join(sorted(domain))))
    return value


def opt_enum(payload, name, domain, default=None):
    if not _present(payload, name):
        return default
    value = req_str(payload, name)
    if value not in domain:
        raise bad("%s must be one of %s." % (name, ", ".join(sorted(domain))))
    return value


def req_date(payload, name):
    value = req_str(payload, name)
    parsed = db.parse_date(value)
    if parsed is None:
        raise bad("%s must be an ISO-8601 date (YYYY-MM-DD)." % name)
    return parsed


def opt_date(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = req_str(payload, name)
    parsed = db.parse_date(value)
    if parsed is None:
        raise bad("%s must be an ISO-8601 date (YYYY-MM-DD)." % name)
    return parsed


def req_datetime(payload, name):
    value = req_str(payload, name)
    parsed = db.parse_datetime(value)
    if parsed is None:
        raise bad("%s must be an ISO-8601 datetime." % name)
    return parsed


def req_fraction(payload, name):
    """A number in the closed interval [0, 1] (PRD 2.5)."""
    if not _present(payload, name):
        raise bad("%s is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("%s must be a number." % name)
    if value < 0 or value > 1:
        raise bad("%s must lie in the closed interval from 0 through 1." % name)
    return value


def req_id(payload, name):
    """A required foreign key: must be a non-empty string."""
    if not _present(payload, name):
        raise bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, str) or value == "":
        raise bad("%s must be a string identifier." % name)
    return value


def opt_id(payload, name):
    if not _present(payload, name):
        return None
    value = payload[name]
    if not isinstance(value, str) or value == "":
        raise bad("%s must be a string identifier." % name)
    return value


def req_string_array(payload, name, domain):
    if not _present(payload, name):
        raise bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, list) or len(value) == 0:
        raise bad("%s must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in domain:
            raise bad("%s may only contain %s." % (name, ", ".join(sorted(domain))))
    return list(value)


# ---------------------------------------------------------------------------
# pagination (PRD 2.3)
# ---------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not _INT_RE.match(raw):
        raise bad("%s must be an integer." % name)
    return int(raw)


def pagination():
    limit = _query_int("limit")
    if limit is None:
        limit = LIMIT_DEFAULT
    elif limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise bad("limit must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX))
    offset = _query_int("offset")
    if offset is None:
        offset = OFFSET_DEFAULT
    elif offset < 0:
        raise bad("offset must not be negative.")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit]


# ---------------------------------------------------------------------------
# query filters
# ---------------------------------------------------------------------------
def query_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise bad("%s must be true or false." % name)


def query_date(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    parsed = db.parse_date(raw)
    if parsed is None:
        raise bad("%s must be an ISO-8601 date (YYYY-MM-DD)." % name)
    return parsed
