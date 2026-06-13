"""Shared route helpers: body parsing, type/enum validation, datetime parsing,
pagination, and serialization stripping.

All structural names (header names, envelope fields, pagination params) trace to
PRD §2.x and the scaffold. ERR_INVALID_REQUEST is the structural-validation
error (priority 5); ERR_VALIDATION_RANGE is the numeric-range error (priority
19) and is raised explicitly by callers, not here.
"""
from datetime import datetime, timezone

from flask import request

from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON as a dict (empty dict if no body).

    A non-object JSON body is a structural error -> ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        # Body present but unparseable.
        if request.data.strip():
            raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    """Ensure each named field is present and not None -> ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % key)
    return v


def check_enum(value, allowed, field_name):
    if value not in allowed:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (field_name, sorted(allowed)),
        )


def require_int(body, key):
    """Required integer field (rejects bool, float, string) -> ERR_INVALID_REQUEST."""
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    return v


def require_number(body, key):
    """Required real number (int or float, not bool) -> ERR_INVALID_REQUEST."""
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    return v


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if value is None or unparseable.
    """
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_dt(body, key):
    """Required ISO 8601 datetime field -> ERR_INVALID_REQUEST on bad shape."""
    raw = body.get(key)
    dt = parse_dt(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 datetime." % key)
    return dt


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    """Parse/validate limit & offset query params.

    There is no dedicated pagination error in this catalog; a malformed value is
    a structural request error -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None or limit_raw == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST", "limit must be within [1,100].")

    if offset_raw is None or offset_raw == "":
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")

    return limit, offset


def paginate(items):
    """Sort by created_at asc (with _seq tie-break), apply limit/offset, and
    build the pagination meta block (PRD §2.3). Returns (page_items, meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def strip_internal(rec):
    """Remove internal-only keys (prefixed with '_') from a serialized view."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
