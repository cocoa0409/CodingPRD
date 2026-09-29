"""Request-shape validation (PRD 2.10 step 6) and pagination (PRD 2.3)."""
import re

from flask import request

import clock
from errors import ApiError

_INT_RE = re.compile(r"^[+-]?\d+$")


def invalid(message="The request is malformed."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


def _missing(data, name):
    return name not in data or data[name] is None


def field_string(data, name, min_len=1, max_len=None, required=True,
                 default=None):
    if _missing(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    if len(value) < min_len:
        invalid("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' is too long." % name)
    return value


def field_enum(data, name, allowed, required=True, default=None):
    if _missing(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def field_number(data, name, minimum=None, maximum=None,
                 exclusive_minimum=False, required=True, default=None):
    if _missing(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % name)
    if minimum is not None:
        if exclusive_minimum and not value > minimum:
            invalid("Field '%s' must be greater than %s." % (name, minimum))
        if not exclusive_minimum and value < minimum:
            invalid("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be at most %s." % (name, maximum))
    return value


def field_int(data, name, minimum=None, maximum=None, required=True,
              default=None):
    if _missing(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be at most %s." % (name, maximum))
    return value


def field_bool(data, name, required=True, default=None):
    if _missing(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def field_datetime(data, name, required=True, default=None):
    if _missing(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    parsed = clock.parse_iso(value)
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


def field_id(data, name, required=True, default=None):
    if _missing(data, name):
        if required:
            invalid("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        invalid("Field '%s' must be a non-empty string identifier." % name)
    return value


def window(start, end, label="window"):
    """PRD 2.10 step 6: every window's end strictly after its start."""
    if start is not None and end is not None and not end > start:
        invalid("The %s end must be strictly after its start." % label)


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not _INT_RE.match(raw.strip()):
            invalid("Query parameter 'limit' must be an integer.")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not _INT_RE.match(raw.strip()):
            invalid("Query parameter 'offset' must be an integer.")
        offset = int(raw.strip())
        if offset < 0:
            invalid("Query parameter 'offset' may not be negative.")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def filter_rows(rows, filters):
    """Exact-match filters taken from the query string."""
    out = list(rows)
    for name, key in filters.items():
        if name in request.args:
            wanted = request.args.get(name)
            out = [r for r in out if str(r.get(key)) == wanted]
    return out
