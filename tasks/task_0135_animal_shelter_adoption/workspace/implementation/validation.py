"""Body-shape, pagination, and field-coercion helpers (PRD §2.3, §2.6, §2.7).

Validation order across a request is enforced by call order in each route:
auth -> authorization -> existence(FK/path 404) -> body shape(422) -> state/business.
"""
from flask import request

import errors

_MISSING = object()


def get_json_body():
    """Return the parsed JSON object, or {} when the body is empty.

    A non-object JSON payload (array, string, number) is an invalid request.
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


def require_string(body, field, allow_empty=False):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field {field} must be a string")
    if not allow_empty and val.strip() == "":
        raise errors.invalid_request(f"Field {field} must not be empty")
    return val


def optional_string(body, field, default=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        return default
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field {field} must be a string")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return val


def optional_int(body, field, default=None, minimum=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return val


def optional_bool(body, field, default=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        return default
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def require_enum(body, field, members):
    val = require_string(body, field)
    if val not in members:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(members)}")
    return val


def optional_enum(body, field, members, default=None):
    val = optional_string(body, field, _MISSING)
    if val is _MISSING or val is None:
        return default
    if val not in members:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(members)}")
    return val


def parse_pagination():
    """Parse & validate limit/offset query params (PRD §2.3).

    limit defaults 10, range [1,100]; offset defaults 0, >= 0. Out of range ->
    ERR_VALIDATION_LIMIT (422).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.validation_limit("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation_limit("limit must be within [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.validation_limit("offset must be an integer")
        if offset < 0:
            raise errors.validation_limit("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list; total_count is the pre-slice length."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
