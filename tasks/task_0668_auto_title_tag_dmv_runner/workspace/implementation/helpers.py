"""Request-body and query-param parsing helpers (PRD §2.3 pagination, §2.9 enums)."""

from flask import request

import errors

# Pagination defaults (PRD §2.3 / scaffold response_envelope.pagination_defaults)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def get_json_body():
    """Return the parsed JSON object body, or {} when no body was sent.

    A body that is present but not a JSON object (or malformed JSON) is a
    malformed request (ERR_INVALID_REQUEST 400).
    """
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # No body sent at all is fine for action endpoints; only treat a present
        # but unparseable body as malformed.
        if (request.data or b"").strip():
            raise errors.invalid_request("Request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def parse_pagination():
    """Parse limit/offset query params with validation (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.invalid_request("limit out of range")

    if raw_offset is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset out of range")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a list after sorting by created_at ASC (PRD §2.3).

    Tie-break on the monotonic per-process seq so order is stable when two
    resources share a created_at millisecond string.
    """
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"{field} is required and must be a non-empty string")
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"{field} is required and must be an integer")
    return val


def opt_int(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"{field} must be an integer")
    return val


def opt_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"{field} must be a boolean")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"{field} must be one of {sorted(allowed)}")
    return val
