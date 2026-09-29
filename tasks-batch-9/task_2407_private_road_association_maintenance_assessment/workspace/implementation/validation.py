"""Request-shape validation — check 4 of PRD 2.10 (ERR_INVALID_REQUEST)."""

from flask import request

from db import parse_date, parse_datetime
from errors import ApiError

MISSING = object()


def bad(field, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def get_body():
    """The parsed JSON object body, or {} when no body was supplied."""
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _present(body, field):
    return field in body and body[field] is not None


# ---------------------------------------------------------------------------
# scalar readers
# ---------------------------------------------------------------------------

def req_str(body, field):
    if not _present(body, field):
        bad(field, "is required")
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        bad(field, "must be a non-empty string")
    return value


def opt_str(body, field, default=None):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        bad(field, "must be a non-empty string")
    return value


def _as_int(field, value, minimum=None, maximum=None):
    if isinstance(value, bool):
        bad(field, "must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not float(value).is_integer():
            bad(field, "must be an integral value")
        number = int(value)
    else:
        bad(field, "must be an integer")
    if minimum is not None and number < minimum:
        bad(field, "must be at least %s" % minimum)
    if maximum is not None and number > maximum:
        bad(field, "must be at most %s" % maximum)
    return number


def req_int(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        bad(field, "is required")
    return _as_int(field, body[field], minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if not _present(body, field):
        return default
    return _as_int(field, body[field], minimum, maximum)


def _as_num(field, value, minimum=None, exclusive_minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(field, "must be a number")
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        bad(field, "must be a finite number")
    if minimum is not None and value < minimum:
        bad(field, "must be at least %s" % minimum)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        bad(field, "must be greater than %s" % exclusive_minimum)
    return value


def req_num(body, field, minimum=None, exclusive_minimum=None):
    if not _present(body, field):
        bad(field, "is required")
    return _as_num(field, body[field], minimum, exclusive_minimum)


def opt_num(body, field, default=None, minimum=None, exclusive_minimum=None):
    if not _present(body, field):
        return default
    return _as_num(field, body[field], minimum, exclusive_minimum)


def req_bool(body, field):
    if not _present(body, field):
        bad(field, "is required")
    value = body[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def opt_bool(body, field, default=None):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(body, field, allowed, default=None):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def req_date(body, field):
    if not _present(body, field):
        bad(field, "is required")
    parsed = parse_date(body[field])
    if parsed is None:
        bad(field, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return parsed


def opt_date(body, field, default=None):
    if not _present(body, field):
        return default
    parsed = parse_date(body[field])
    if parsed is None:
        bad(field, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return parsed


def req_dt(body, field):
    if not _present(body, field):
        bad(field, "is required")
    parsed = parse_datetime(body[field])
    if parsed is None:
        bad(field, "must be an ISO 8601 instant")
    return parsed


def opt_dt(body, field, default=None):
    if not _present(body, field):
        return default
    parsed = parse_datetime(body[field])
    if parsed is None:
        bad(field, "must be an ISO 8601 instant")
    return parsed


# ---------------------------------------------------------------------------
# query parameters
# ---------------------------------------------------------------------------

def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        text = raw_limit.strip()
        try:
            limit = int(text)
        except (TypeError, ValueError):
            bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            bad("limit", "must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        text = raw_offset.strip()
        try:
            offset = int(text)
        except (TypeError, ValueError):
            bad("offset", "must be an integer of at least 0")
        if offset < 0:
            bad("offset", "must be at least 0")
    return limit, offset


def query_enum(field, allowed):
    value = request.args.get(field)
    if value is None:
        return None
    value = value.strip()
    if value not in allowed:
        bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def query_str(field):
    value = request.args.get(field)
    if value is None:
        return None
    value = value.strip()
    if not value:
        bad(field, "must be a non-empty string")
    return value


def query_int(field, minimum=None, maximum=None):
    value = request.args.get(field)
    if value is None:
        return None
    try:
        number = int(value.strip())
    except (TypeError, ValueError):
        bad(field, "must be an integer")
    if minimum is not None and number < minimum:
        bad(field, "must be at least %s" % minimum)
    if maximum is not None and number > maximum:
        bad(field, "must be at most %s" % maximum)
    return number


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
