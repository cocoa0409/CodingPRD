"""Input validation + pagination helpers.

Error precedence for malformed input (PRD §3.11):
  - missing required field / type mismatch / out-of-range numeric -> ERR_INVALID_REQUEST (400)
  - enum value outside declared set                               -> ERR_INVALID_ENUM_VALUE (400)
  - pagination out of bounds                                      -> ERR_INVALID_PAGINATION (400)
"""
from flask import request

from errors import ApiError


def get_json_body():
    """Return the parsed JSON object body, or {} when empty. Malformed JSON -> ERR_INVALID_REQUEST."""
    if request.method in ("POST", "PUT", "PATCH"):
        raw = request.get_data(cache=True)
        if raw is None or raw.strip() == b"":
            return {}
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return body
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return val


def _is_number(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def require_number(body, field):
    val = require(body, field)
    if not _is_number(val):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return val


def optional_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_number(val):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def optional_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    if val not in allowed:
        raise ApiError("ERR_INVALID_ENUM_VALUE", "Field %s has invalid value: %s" % (field, val))
    return val


def parse_pagination():
    """Parse limit/offset query params. Defaults limit=10 (min 1, max 100), offset=0 (min 0)."""
    args = request.args

    limit = 10
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")

    offset = 0
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Return (page, pagination_meta). items must already be sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
