"""Request-shape validation (check 5) and pagination parsing (PRD 2.3)."""
from flask import request

from errors import ApiError
from util import parse_dt

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise bad("Request body must be a JSON object.")
    return payload


def _present(data, field):
    return field in data and data[field] is not None


def req_fk(data, field):
    """A foreign key that is not supplied at all is a shape error, not a 404."""
    if not _present(data, field):
        raise bad("Field '%s' is required." % field)
    return data[field]


def req_str(data, field, non_empty=True):
    if not _present(data, field):
        raise bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % field)
    if non_empty and value.strip() == "":
        raise bad("Field '%s' must be non-empty." % field)
    return value


def opt_str(data, field, non_empty=False, default=None):
    if not _present(data, field):
        return default
    return req_str(data, field, non_empty=non_empty)


def req_int(data, field, minimum=None, maximum=None):
    if not _present(data, field):
        raise bad("Field '%s' is required." % field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def req_num(data, field, minimum=None, maximum=None):
    if not _present(data, field):
        raise bad("Field '%s' is required." % field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % field)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def req_bool(data, field):
    if not _present(data, field):
        raise bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, default=False):
    if not _present(data, field):
        return default
    return req_bool(data, field)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        raise bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if not _present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_dt(data, field):
    raw = req_str(data, field)
    parsed = parse_dt(raw)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 instant." % field)
    return parsed


def req_str_array(data, field, non_empty=True):
    if not _present(data, field):
        raise bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % field)
    if non_empty and len(value) == 0:
        raise bad("Field '%s' must be a non-empty array." % field)
    for item in value:
        if not isinstance(item, str):
            raise bad("Field '%s' must contain only strings." % field)
    return list(value)


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad("limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise bad("limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad("offset must be an integer.")
        if offset < 0:
            raise bad("offset must be >= 0.")
    return limit, offset


def q(name):
    return request.args.get(name)


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
