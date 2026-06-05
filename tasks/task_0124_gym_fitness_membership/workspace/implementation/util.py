"""Shared helpers: input parsing/validation, datetime, pagination, serialize."""
from datetime import datetime, timezone

import errors
from response import iso_ms

# Pagination defaults (SCAFFOLD §1.0 pagination_defaults).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, fields):
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    for f in fields:
        if f not in body or body[f] is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field '%s'" % f)


def require_str(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str) or v == "":
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string" % field)
    return v


def require_int(body, field, minimum=None, maximum=None):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s" % (field, maximum))
    return v


def optional_number(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number" % field)
    if minimum is not None and v < minimum:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s" % (field, maximum))
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def parse_pagination(args):
    """Return (limit, offset) from query args with defaults/min/max enforced."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN:
            limit = PAGE_LIMIT_MIN
        if limit > PAGE_LIMIT_MAX:
            limit = PAGE_LIMIT_MAX
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3) then slice.

    Items carry a hidden monotonic '_seq' so the ascending created_at order is
    total even when the logical clock does not advance between creates.
    """
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, pagination


def public(record):
    """Strip internal-only keys (those prefixed with '_') for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]


def fmt_dt(dt):
    if dt is None:
        return None
    return iso_ms(dt)
