"""Request-shape validation (validation priority 6 -> ERR_INVALID_REQUEST 422)."""
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_MISSING = object()


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body_dict():
    raw = request.get_data()
    if raw is None or not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise invalid("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# scalar field helpers
# ---------------------------------------------------------------------------
def _present(body, field):
    return field in body and body[field] is not None


def field_str(body, field, required=True, default=None, min_len=1, max_len=None):
    if not _present(body, field):
        if required:
            raise invalid("Field '%s' is required" % field)
        return default
    value = body[field]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string" % field)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' must be at least %d characters" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters" % (field, max_len))
    return value


def field_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, field):
        if required:
            raise invalid("Field '%s' is required" % field)
        return default
    value = body[field]
    if isinstance(value, bool):
        raise invalid("Field '%s' must be an integer" % field)
    if isinstance(value, int):
        ivalue = value
    elif isinstance(value, float) and float(value).is_integer():
        ivalue = int(value)
    else:
        raise invalid("Field '%s' must be an integer" % field)
    if minimum is not None and ivalue < minimum:
        raise invalid("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and ivalue > maximum:
        raise invalid("Field '%s' must be <= %s" % (field, maximum))
    return ivalue


def field_decimal(body, field, required=True, default=None, minimum=None,
                  maximum=None, max_decimals=None):
    if not _present(body, field):
        if required:
            raise invalid("Field '%s' is required" % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number" % field)
    try:
        dvalue = Decimal(str(value))
    except InvalidOperation:
        raise invalid("Field '%s' must be a number" % field)
    if max_decimals is not None:
        exponent = dvalue.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -max_decimals:
            raise invalid("Field '%s' allows at most %d decimal places" % (field, max_decimals))
    if minimum is not None and dvalue < Decimal(str(minimum)):
        raise invalid("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and dvalue > Decimal(str(maximum)):
        raise invalid("Field '%s' must be <= %s" % (field, maximum))
    return dvalue


def field_bool(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            raise invalid("Field '%s' is required" % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean" % field)
    return value


def field_enum(body, field, allowed, required=True, default=None):
    if not _present(body, field):
        if required:
            raise invalid("Field '%s' is required" % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def parse_date(value, field):
    if not isinstance(value, str) or len(value) != 10:
        raise invalid("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)" % field)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise invalid("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)" % field)


def field_date(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            raise invalid("Field '%s' is required" % field)
        return default
    return parse_date(body[field], field)


def field_id(body, field, required=True):
    """Reference field: must be a non-empty string when present."""
    if not _present(body, field):
        if required:
            raise invalid("Field '%s' is required" % field)
        return None
    value = body[field]
    if not isinstance(value, str) or not value:
        raise invalid("Field '%s' must be a string identifier" % field)
    return value


def ref_value(body, field):
    """Raw reference value used by the priority-5 existence pass.

    Returns None when the field is absent, null or not a usable string; shape
    validation (priority 6) reports those cases later.
    """
    if not _present(body, field):
        return None
    value = body[field]
    if isinstance(value, str) and value:
        return value
    return None


# ---------------------------------------------------------------------------
# query-parameter helpers
# ---------------------------------------------------------------------------
def query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        raise invalid("Query parameter '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Query parameter '%s' must be <= %s" % (name, maximum))
    return value


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise invalid("Query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def pagination():
    """PRD 2.3: limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = query_int("limit", 10, 1, 100)
    offset = query_int("offset", 0, 0, None)
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
