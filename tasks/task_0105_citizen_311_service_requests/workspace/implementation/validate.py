"""Input parsing, schema validation, and pagination helpers.

Schema violations (missing required field, bad enum, wrong type) and
out-of-range pagination -> ERR_INVALID_REQUEST (422) (priority 18 / §2.3).
"""
from flask import request

import errors

PRIORITIES = {"LOW", "STANDARD", "HIGH", "EMERGENCY"}
NOTIFY_CHANNELS = {"EMAIL", "SMS", "NONE"}
WINDOW_TYPES = {"MAINTENANCE", "BLACKOUT"}


def body():
    """Return the JSON body as a dict; missing/empty body -> {}; non-object -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise errors.invalid_request("Missing required field: {}".format(field))
    return data[field]


def require_str(data, field):
    val = require(data, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field {} must be a non-empty string.".format(field))
    return val


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if not isinstance(val, str):
        raise errors.invalid_request("Field {} must be a string.".format(field))
    return val


def require_number(data, field):
    val = require(data, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field {} must be a number.".format(field))
    return val


def opt_number(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field {} must be a number.".format(field))
    return val


def require_int(data, field):
    val = require(data, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field {} must be an integer.".format(field))
    return val


def opt_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field {} must be a boolean.".format(field))
    return val


def require_enum(data, field, allowed):
    val = require(data, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request("Field {} must be one of {}.".format(field, sorted(allowed)))
    return val


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request("Field {} must be one of {}.".format(field, sorted(allowed)))
    return val


def pagination():
    """Parse limit/offset query params (§2.3). Out-of-range -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    """Slice an already-sorted list; return (page_items, total_count)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
