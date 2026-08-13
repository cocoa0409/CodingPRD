"""Shared route helpers — pagination, validation, body parsing."""
from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def get_json_body():
    """Parse JSON body, returning a dict. Empty body -> {}.

    Raises ERR_INVALID_REQUEST for malformed JSON.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be valid JSON", 400)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def parse_pagination():
    """Parse limit/offset query params with defaults from SCAFFOLD §1.0.

    Defaults: limit=10 (min 1, max 100), offset=0.
    """
    try:
        limit_raw = request.args.get("limit", "10")
        offset_raw = request.args.get("offset", "0")
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


def apply_pagination(items, limit, offset):
    """Sort by created_at ascending, then paginate.

    PRD §2.3 mandates ordering by created_at only. The logical clock makes
    timestamp ties common, and Python's sort is stable, so ties retain
    insertion (creation) order — a random-id tiebreak would scramble the
    audit trail.
    """
    items_sorted = sorted(items, key=lambda x: x["created_at"])
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, total


def require_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a non-empty string", 400)
    return v


def require_int(body, field, positive=False, min_value=None, max_value=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an integer", 400)
    if positive and v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be positive", 400)
    if min_value is not None and v < min_value:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {min_value}", 400)
    if max_value is not None and v > max_value:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be <= {max_value}", 400)
    return v


def optional_int(body, field, default, positive=False, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, positive=positive, min_value=min_value, max_value=max_value)


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a boolean", 400)
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)


def require_enum(body, field, allowed):
    v = body.get(field)
    if v is None or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{field}' must be one of {sorted(allowed)}",
            400,
        )
    return v


def require_date(body, field):
    """ISO YYYY-MM-DD date string."""
    v = require_str(body, field)
    from datetime import date
    try:
        date.fromisoformat(v)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be ISO YYYY-MM-DD", 400)
    return v


def lookup_or_404(store: dict, key: str, label: str = "Resource"):
    if key is None or key not in store:
        raise ApiError(ERR_NOT_FOUND, f"{label} not found", 404)
    return store[key]
