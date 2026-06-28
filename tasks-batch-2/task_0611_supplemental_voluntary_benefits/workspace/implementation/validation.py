"""Request parsing, pagination, and field-level validation helpers.

Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0,
min 0. Out-of-bounds -> ERR_VALIDATION_PAGINATION. Field-level body validation
(PRD §2.10 priority 16) -> ERR_INVALID_REQUEST.
"""

from flask import request

import errors

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if no body)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def parse_pagination():
    """Parse and validate `limit`/`offset` query params (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.validation_pagination("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.validation_pagination(
                f"limit must be between {LIMIT_MIN} and {LIMIT_MAX}"
            )

    if raw_offset is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.validation_pagination("offset must be an integer")
        if offset < 0:
            raise errors.validation_pagination("offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Apply window; return (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise errors.invalid_request(f"'{field}' is required and must be a non-empty string")
    return val


def optional_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str):
        raise errors.invalid_request(f"'{field}' must be a string")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"'{field}' is required and must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"'{field}' must be >= {minimum}")
    return val


def optional_int(body, field, default=None, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"'{field}' must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"'{field}' must be >= {minimum}")
    return val


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"'{field}' must be a boolean")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            f"'{field}' must be one of {sorted(allowed)}"
        )
    return val


def require_datetime(body, field):
    """Parse a required ISO 8601 datetime field; raise ERR_INVALID_REQUEST on bad value."""
    from clock import parse_iso8601
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise errors.invalid_request(f"'{field}' is required and must be an ISO 8601 string")
    try:
        return parse_iso8601(val)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"'{field}' must be a valid ISO 8601 datetime")
