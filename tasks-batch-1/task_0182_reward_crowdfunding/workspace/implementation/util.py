"""Shared helpers: datetime parsing, pagination, body access, serialization filters."""
from datetime import datetime, timezone

from flask import request

from errors import err, ERR_INVALID_REQUEST, ERR_VALIDATION_PAGINATION


def parse_dt(value):
    """Parse an ISO 8601 UTC datetime string into an aware datetime.

    Accepts trailing 'Z' or explicit offset. Returns None if value is not a
    parseable string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_json_body():
    """Return the request JSON body as a dict (empty dict if none/invalid)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string" % field)
    return v


def require_positive_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    if v <= 0:
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be > 0" % field)
    return v


def require_nonneg_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    if v < 0:
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be >= 0" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST,
                  "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def optional_limit_quantity(body):
    """limit_quantity: null/omitted => None (unlimited); else must be int > 0."""
    if "limit_quantity" not in body or body.get("limit_quantity") is None:
        return None
    v = body.get("limit_quantity")
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise err(ERR_INVALID_REQUEST, "limit_quantity must be a positive integer or null")
    return v


def parse_pagination():
    """Parse limit/offset query params with PRD §2.3 defaults and bounds.

    limit default 10, range [1,100]; offset default 0, >= 0.
    Out of range -> ERR_VALIDATION_PAGINATION (422).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PAGINATION, "limit must be an integer")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PAGINATION, "offset must be an integer")

    if limit < 1 or limit > 100:
        raise err(ERR_VALIDATION_PAGINATION, "limit must be in [1, 100]")
    if offset < 0:
        raise err(ERR_VALIDATION_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by (created_at, _seq) ascending, then apply limit/offset window.

    Returns (page_serialized, total_count). `records` is a list of internal
    entity dicts; caller passes already-serialized output via serializer.
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
