"""Shared request-parsing, pagination, datetime, and computed-field helpers."""
from datetime import datetime, timezone

from flask import request

import errors

# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON body as a dict. Absent/empty body -> {} (many POSTs take no body).

    A body that is present but not a JSON object is a malformed request.
    """
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


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}.")
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string.")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}.")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}.")
    return val


def require_int(body, field):
    val = require(body, field)
    # bool is a subclass of int; reject it as a wrong type.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    return val


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean.")
    return val


def require_enum_array(body, field, allowed, optional=False):
    """Parse a list field whose members must each be in `allowed`. Deduplicated set preserved as-is in storage."""
    if field not in body or body[field] is None:
        if optional:
            return []
        raise errors.invalid_request(f"Missing required field: {field}.")
    val = body[field]
    if not isinstance(val, list):
        raise errors.invalid_request(f"Field {field} must be an array.")
    for item in val:
        if not isinstance(item, str) or item not in allowed:
            raise errors.invalid_request(f"Field {field} members must each be one of {sorted(allowed)}.")
    return val


# ---------------------------------------------------------------------------
# Datetime
# ---------------------------------------------------------------------------

def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise errors.invalid_request(f"Field {field} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_dt(body, field):
    val = require(body, field)
    return parse_dt(val, field)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Out-of-range -> ERR_INVALID_REQUEST (422), the basic shape validation.
# ---------------------------------------------------------------------------

def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (oldest first), then slice. Returns (page, total_count)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
