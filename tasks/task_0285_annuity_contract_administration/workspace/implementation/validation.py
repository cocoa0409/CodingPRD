"""Shared input parsing / shape validation helpers (PRD §2.3, §2.9).

These raise ERR_INVALID_REQUEST (422) for shape/range problems. Existence and
state checks live in the service layer.
"""

from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Parse the JSON body; an absent body is treated as {}. A present but
    malformed (non-object) body is ERR_INVALID_REQUEST."""
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


def parse_pagination():
    """Return (limit, offset). Out-of-range values are ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        limit = _to_int(limit_raw, "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.invalid_request(
                "limit must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
            )

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        offset = _to_int(offset_raw, "offset")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def _to_int(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise errors.invalid_request("%s must be an integer." % name)


def require_present(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s." % field)
    return body[field]


def require_int(body, field, *, minimum=None, maximum=None, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s." % field)
        return default
    value = body[field]
    # Reject bools (which are ints in Python) and non-int types.
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise errors.invalid_request("%s must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise errors.invalid_request("%s must be <= %d." % (field, maximum))
    return value


def require_string(body, field, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s." % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("%s must be a non-empty string." % field)
    return value


def require_enum(body, field, allowed, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s." % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        raise errors.invalid_request(
            "%s must be one of %s." % (field, sorted(allowed))
        )
    return value


def require_bool(body, field, *, required=False, default=False):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s." % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise errors.invalid_request("%s must be a boolean." % field)
    return value


def optional_string(body, field):
    """Return a string FK reference, or None if absent/null. Type-checked."""
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("%s must be a string." % field)
    return value


def parse_query_bool(name, default):
    """Parse a boolean query param. Accepts 'true'/'false' case-insensitively."""
    raw = request.args.get(name)
    if raw is None:
        return default
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise errors.invalid_request("%s must be a boolean." % name)
