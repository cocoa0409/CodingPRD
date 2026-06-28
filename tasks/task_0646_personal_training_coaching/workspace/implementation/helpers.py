"""Request parsing, validation, and pagination helpers (PRD §2.3, §2.6)."""

from flask import request

import errors
from clock import parse_iso8601


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when no body was sent.

    A malformed (non-JSON) body raises ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, *names):
    for name in names:
        if name not in body or body[name] is None:
            raise errors.invalid_request(f"Missing required field: {name}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return value


def require_positive_number(value, field):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise errors.invalid_request(f"Field {field} must be a positive number")
    if value <= 0:
        raise errors.invalid_request(f"Field {field} must be greater than zero")
    return value


def require_positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {field} must be a positive integer")
    if value <= 0:
        raise errors.invalid_request(f"Field {field} must be greater than zero")
    return value


def require_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return value


def parse_required_datetime(value, field):
    try:
        return parse_iso8601(value)
    except Exception:
        raise errors.invalid_request(f"Field {field} must be a valid ISO 8601 datetime")


def pagination_params():
    """Parse limit/offset query params (PRD §2.3): limit default 10, min 1, max 100;
    offset default 0, min 0. Out-of-range/non-integer values are rejected with
    ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Slice already-sorted items; return (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
