"""Shared helpers: pagination parsing, body validation, datetime parsing.

Pagination params/defaults read verbatim from SCAFFOLD response_envelope /
PRD §2.3: limit default 10 (1..100), offset default 0 (>=0).
"""
from datetime import datetime, timezone

from flask import request

import errors
from errors import ApiError


def get_json_body():
    """Parse request JSON. Missing/invalid body -> empty dict (then field checks fire)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return body


def parse_pagination():
    """Returns (limit, offset). ERR_PAGINATION_INVALID on out-of-bounds (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_PAGINATION_INVALID, 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_PAGINATION_INVALID, 422, "limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_PAGINATION_INVALID, 422, "offset must be >= 0")
        if offset < 0:
            raise ApiError(errors.ERR_PAGINATION_INVALID, 422, "offset must be >= 0")

    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ascending (PRD §2.3), then slice."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"Missing required field: {name}")


def require_string(body, name):
    val = body.get(name)
    if not isinstance(val, str) or not val.strip():
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be a non-empty string")
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be an integer")
    if minimum is not None and val < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be <= {maximum}")
    return val


def optional_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum=minimum, maximum=maximum)


def require_number(body, name, minimum=None, maximum=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be a number")
    if minimum is not None and val < minimum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be <= {maximum}")
    return val


def optional_number(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return require_number(body, name, minimum=minimum, maximum=maximum)


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{name} must be a boolean")
    return val


def require_enum(body, name, allowed):
    val = body.get(name)
    if not isinstance(val, str) or val not in allowed:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       f"{name} must be one of {sorted(allowed)}")
    return val


def parse_datetime(value, field_name):
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    if not isinstance(value, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{field_name} must be an ISO 8601 string")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"{field_name} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
