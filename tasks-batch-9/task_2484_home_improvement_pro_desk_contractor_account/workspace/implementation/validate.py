"""Request-shape validation (rung 5) and pagination parsing (PRD 2.3)."""
from flask import request

import clock
import db
from errors import ApiError, invalid

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise invalid("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object.")
    return payload


def req_str(data, name, allow_empty=False):
    value = data.get(name)
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        raise invalid("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(data, name, default=None):
    if name not in data or data.get(name) is None:
        return default
    value = data.get(name)
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if name not in data or data.get(name) is None:
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_number(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be <= %s." % (name, maximum))
    return value


def req_bool(data, name):
    value = data.get(name)
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=False):
    if name not in data or data.get(name) is None:
        return default
    value = data.get(name)
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def req_enum(data, name, allowed):
    value = data.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data.get(name) is None:
        return default
    return req_enum(data, name, allowed)


def req_datetime(data, name):
    value = data.get(name)
    parsed = clock.parse_datetime(value)
    if parsed is None:
        raise invalid("Field '%s' must be an ISO-8601 instant." % name)
    return parsed


def req_date(data, name):
    value = data.get(name)
    parsed = clock.parse_date(value)
    if parsed is None:
        raise invalid("Field '%s' must be an ISO date (YYYY-MM-DD)." % name)
    return parsed


def req_array(data, name):
    value = data.get(name)
    if not isinstance(value, list) or len(value) == 0:
        raise invalid("Field '%s' must be a non-empty array." % name)
    return value


def req_string_array(data, name, allowed=None):
    value = req_array(data, name)
    for item in value:
        if not isinstance(item, str) or (allowed is not None and item not in allowed):
            raise invalid("Field '%s' contains an unsupported value." % name)
    return value


def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise invalid("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(records, serializer=None):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    render = serializer or db.public
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [render(r) for r in page], meta


def resolve_fk(data, name, table, error_id):
    """Rung 4: a body reference that is present but does not resolve is a 404.

    An absent reference is left to the rung-5 shape check.
    """
    if name not in data or data.get(name) is None:
        return None
    value = data.get(name)
    rec = db.get(table, value) if isinstance(value, str) else None
    if rec is None:
        raise ApiError(error_id, 404)
    return rec
