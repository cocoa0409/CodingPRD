"""Request-body / query-param validation helpers.

All produce ERR_INVALID_REQUEST (422) on failure, matching validation
priority 4 in the scaffold. Pagination out-of-range is also
ERR_INVALID_REQUEST (PRD 2.3).
"""
from datetime import datetime, timezone

from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def body():
    """Parse the JSON body. Missing/empty body -> empty dict.

    A body that is present but not a JSON object -> ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require(data, field):
    if field not in data or data[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return data[field]


def require_str(data, field, allow_empty=False):
    v = require(data, field)
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {field} must be a string")
    if not allow_empty and v.strip() == "":
        raise errors.invalid_request(f"Field {field} must be non-empty")
    return v


def opt_str(data, field, default=None, allow_empty=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {field} must be a string")
    if not allow_empty and v.strip() == "":
        raise errors.invalid_request(f"Field {field} must be non-empty")
    return v


def require_int(data, field, minimum=None, maximum=None, exclusive_min=None):
    v = require(data, field)
    if not is_int(v):
        raise errors.invalid_request(f"Field {field} must be an integer")
    _range_check(field, v, minimum, maximum, exclusive_min)
    return v


def opt_int(data, field, default=0, minimum=None, maximum=None, exclusive_min=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not is_int(v):
        raise errors.invalid_request(f"Field {field} must be an integer")
    _range_check(field, v, minimum, maximum, exclusive_min)
    return v


def require_number(data, field, minimum=None, maximum=None, exclusive_min=None):
    v = require(data, field)
    if not is_number(v):
        raise errors.invalid_request(f"Field {field} must be a number")
    _range_check(field, v, minimum, maximum, exclusive_min)
    return v


def opt_number(data, field, default=0, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not is_number(v):
        raise errors.invalid_request(f"Field {field} must be a number")
    _range_check(field, v, minimum, maximum)
    return v


def require_bool(data, field):
    v = require(data, field)
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return v


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return v


def require_enum(data, field, allowed):
    v = require(data, field)
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            f"Field {field} must be one of {sorted(allowed)}"
        )
    return v


def _range_check(field, v, minimum, maximum, exclusive_min=None):
    if exclusive_min is not None and not (v > exclusive_min):
        raise errors.invalid_request(f"Field {field} must be > {exclusive_min}")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"Field {field} must be <= {maximum}")


def parse_datetime(data, field, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return default
    v = data[field]
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 string")
    return parse_iso(v, field)


def parse_iso(v, field="datetime"):
    s = v
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise errors.invalid_request(f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination():
    """Parse limit/offset query params. Out-of-range -> ERR_INVALID_REQUEST."""
    args = request.args

    raw_limit = args.get("limit")
    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.invalid_request("limit must be between 1 and 100")

    raw_offset = args.get("offset")
    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


def query_bool(name):
    """Parse a boolean query param ('true'/'false'). Returns None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise errors.invalid_request(f"Query param {name} must be a boolean")
