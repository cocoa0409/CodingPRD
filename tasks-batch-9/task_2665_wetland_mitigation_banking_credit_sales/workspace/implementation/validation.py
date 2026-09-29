"""Schema validation (validation priority 10 -> ERR_INVALID_REQUEST) and
query-parameter parsing (PRD 2.3, 2.10)."""
import re

from flask import request

from errors import ApiError, bad_request
from util import dec, decimal_places, parse_ts

HUC8_RE = re.compile(r"^[0-9]{8}$")
PERMIT_RE = re.compile(r"^[A-Z]{3}-[0-9]{4}-[0-9]{5}$")

_MISSING = object()


def json_body(required=True):
    body = request.get_json(silent=True, force=True)
    if body is None:
        if required:
            raise bad_request("A JSON object request body is required.")
        return {}
    if not isinstance(body, dict):
        raise bad_request("The request body must be a JSON object.")
    return body


def _raw(body, name, required):
    if name not in body or body[name] is None:
        if required:
            raise bad_request("Required field '%s' is missing." % name)
        return _MISSING
    return body[name]


def v_string(body, name, required=True, max_len=None, pattern=None, default=None,
             allow_empty=False):
    raw = _raw(body, name, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, str):
        raise bad_request("Field '%s' must be a string." % name)
    if not allow_empty and not raw.strip():
        raise bad_request("Field '%s' must be a non-empty string." % name)
    if max_len is not None and len(raw) > max_len:
        raise bad_request("Field '%s' exceeds %d characters." % (name, max_len))
    if pattern is not None and not pattern.match(raw):
        raise bad_request("Field '%s' is malformed." % name)
    return raw


def v_enum(body, name, allowed, required=True, default=None):
    raw = _raw(body, name, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, str) or raw not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def v_int(body, name, required=True, minimum=None, default=None):
    raw = _raw(body, name, required)
    if raw is _MISSING:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise bad_request("Field '%s' must be an integer." % name)
    if isinstance(raw, float):
        if not float(raw).is_integer():
            raise bad_request("Field '%s' must be an integer." % name)
        raw = int(raw)
    if minimum is not None and raw < minimum:
        raise bad_request("Field '%s' must be >= %s." % (name, minimum))
    return int(raw)


def v_decimal(body, name, required=True, places=2, minimum=None, min_exclusive=None,
              maximum=None, default=None):
    raw = _raw(body, name, required)
    if raw is _MISSING:
        return default
    return coerce_decimal(raw, name, places=places, minimum=minimum,
                          min_exclusive=min_exclusive, maximum=maximum)


def coerce_decimal(raw, name, places=2, minimum=None, min_exclusive=None, maximum=None):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise bad_request("Field '%s' must be a number." % name)
    value = dec(raw)
    if places is not None and decimal_places(value) > places:
        raise bad_request("Field '%s' carries more than %d decimal places." % (name, places))
    if min_exclusive is not None and value <= dec(min_exclusive):
        raise bad_request("Field '%s' must be greater than %s." % (name, min_exclusive))
    if minimum is not None and value < dec(minimum):
        raise bad_request("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > dec(maximum):
        raise bad_request("Field '%s' must be <= %s." % (name, maximum))
    return value


def v_datetime(body, name, required=True, default=None):
    raw = _raw(body, name, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, str):
        raise bad_request("Field '%s' must be an ISO 8601 timestamp string." % name)
    parsed = parse_ts(raw)
    if parsed is None:
        raise bad_request("Field '%s' is not a valid ISO 8601 timestamp." % name)
    return parsed


def v_array(body, name, required=True, min_len=None, max_len=None):
    raw = _raw(body, name, required)
    if raw is _MISSING:
        return None
    if not isinstance(raw, list):
        raise bad_request("Field '%s' must be an array." % name)
    if min_len is not None and len(raw) < min_len:
        raise bad_request("Field '%s' must carry at least %d entries." % (name, min_len))
    if max_len is not None and len(raw) > max_len:
        raise bad_request("Field '%s' must carry at most %d entries." % (name, max_len))
    return raw


def v_window(body):
    """Half-open window pair; window_end must fall strictly after window_start."""
    start = v_datetime(body, "window_start")
    end = v_datetime(body, "window_end")
    if not end > start:
        raise bad_request("window_end must fall strictly after window_start.")
    return start, end


def v_huc8(body, name, required=True):
    return v_string(body, name, required=required, pattern=HUC8_RE)


# ------------------------------------------------------------------ query args
def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = 10
    else:
        limit_value = _query_int("limit", limit)
        if limit_value < 1 or limit_value > 100:
            raise bad_request("limit must lie within 1 through 100.")
    if offset is None or offset == "":
        offset_value = 0
    else:
        offset_value = _query_int("offset", offset)
        if offset_value < 0:
            raise bad_request("offset may not be negative.")
    return limit_value, offset_value


def _query_int(name, raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad_request("Query parameter '%s' is not a recognised value." % name)
    return raw


def filter_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
