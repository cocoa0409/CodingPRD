"""Request-shape validation helpers (PRD 2.12 step 2 -> ERR_INVALID_REQUEST)."""
import json
import re

from flask import request

from clock import parse_iso
from errors import ApiError, bad_request

MISSING = object()


def get_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise bad_request("Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


def present(body, key):
    return key in body and body[key] is not None


def _raw(body, key):
    if key not in body:
        return MISSING
    return body[key]


def field_str(body, key, required=True, min_len=1, max_len=None, pattern=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' is too long." % key)
    if pattern is not None and not re.match(pattern, value):
        raise bad_request("Field '%s' does not match the required format." % key)
    return value


def field_int(body, key, required=True, minimum=None, maximum=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' is above its maximum." % key)
    return value


def field_number(body, key, required=True, minimum=None, exclusive_minimum=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its minimum." % key)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise bad_request("Field '%s' must be greater than %s." % (key, exclusive_minimum))
    return value


def field_bool(body, key, required=True, default=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return default
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return value


def field_enum(body, key, allowed, required=True):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def field_datetime(body, key, required=True):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    parsed = parse_iso(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def field_str_array(body, key, allowed, required=True, non_empty=True):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % key)
    if non_empty and len(value) == 0:
        raise bad_request("Field '%s' must not be empty." % key)
    for item in value:
        if not isinstance(item, str) or (allowed is not None and item not in allowed):
            raise bad_request("Field '%s' contains an unsupported value." % key)
    return list(value)


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------

def pagination_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = 10
    else:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit_value < 1 or limit_value > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if offset is None or offset == "":
        offset_value = 0
    else:
        try:
            offset_value = int(offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset_value < 0:
            raise bad_request("Query parameter 'offset' must not be negative.")
    return limit_value, offset_value


def paginate(records, serializer):
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [serializer(r) for r in page], meta


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise bad_request("Query parameter '%s' has an unsupported value." % name)
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int(name, minimum=None, maximum=None):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise bad_request("Query parameter '%s' must be an integer." % name)
    if minimum is not None and parsed < minimum:
        raise bad_request("Query parameter '%s' is out of range." % name)
    if maximum is not None and parsed > maximum:
        raise bad_request("Query parameter '%s' is out of range." % name)
    return parsed


def require_no_unknown_enum(value, allowed, key):
    if value is not None and value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is invalid." % key)
    return value
