"""Shared request-parsing, validation, and pagination helpers."""
from datetime import date

from flask import request

from errors import err

# Pagination defaults (scaffold response_envelope.pagination_defaults)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent.

    A body that is present but not a JSON object is malformed -> ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    """Ensure each named field is present and non-null. -> ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return val


def require_nonneg_int(body, field):
    """Validate a present field is a non-negative integer."""
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if val < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-negative")
    return val


def optional_nonneg_int(body, field):
    """If the field is present and non-null, validate non-negative integer."""
    if field in body and body[field] is not None:
        return require_nonneg_int(body, field)
    return None


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return val


def parse_date(value, field):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a valid YYYY-MM-DD date")


def date_diff_days(later_str, earlier_str):
    """Return (later - earlier) in whole days. Inputs are YYYY-MM-DD strings."""
    later = date.fromisoformat(later_str)
    earlier = date.fromisoformat(earlier_str)
    return (later - earlier).days


def paginate():
    """Read and validate limit/offset query params.

    Returns (limit, offset). Out-of-range -> ERR_VALIDATION (422).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise err("ERR_VALIDATION", "limit out of range")

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset out of range")

    return limit, offset


def list_response(items, limit, offset):
    """Sort by created_at ascending, page, and build pagination meta.

    Returns (page_items, pagination_meta).
    """
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination
