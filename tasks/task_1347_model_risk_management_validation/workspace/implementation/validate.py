"""Pipeline stage 2: request-body shape validation, plus pagination parsing.

Every extractor raises ERR_INVALID_REQUEST (400) on a missing required field,
a type mismatch, or an out-of-range enum value.
"""
import math

from flask import request

from errors import ApiError
from utils import parse_iso


def _invalid(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _invalid("Request body must be a JSON object")
    return data


def v_str(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise _invalid("Field '%s' is required and must be a string" % field)
    return val


def v_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise _invalid(
            "Field '%s' is required and must be one of %s" % (field, sorted(allowed))
        )
    return val


def v_bool(body, field):
    val = body.get(field)
    if not isinstance(val, bool):
        raise _invalid("Field '%s' is required and must be a boolean" % field)
    return val


def v_opt_bool(body, field, default=False):
    if field not in body:
        return default
    return v_bool(body, field)


def v_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise _invalid("Field '%s' is required and must be an integer" % field)
    if minimum is not None and val < minimum:
        raise _invalid("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise _invalid("Field '%s' must be <= %s" % (field, maximum))
    return val


def v_number(body, field):
    val = body.get(field)
    if (
        isinstance(val, bool)
        or not isinstance(val, (int, float))
        or (isinstance(val, float) and not math.isfinite(val))
    ):
        raise _invalid("Field '%s' is required and must be a number" % field)
    return val


def v_dt(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise _invalid("Field '%s' is required and must be an ISO 8601 timestamp" % field)
    try:
        return parse_iso(val)
    except Exception:
        raise _invalid("Field '%s' must be a valid ISO 8601 timestamp" % field)


def pagination_params():
    """limit: default 10, clamped to [1, 100]; offset: default 0, clamped to >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise _invalid("Query parameter 'limit' must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise _invalid("Query parameter 'offset' must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
