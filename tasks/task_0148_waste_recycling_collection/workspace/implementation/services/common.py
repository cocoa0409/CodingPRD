"""Shared route helpers: body parsing, pagination, listing."""
from flask import request

from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the request JSON as a dict (empty dict if no body)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    """Ensure each named field is present (and not None) -> ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def check_enum(value, allowed, field_name):
    if value not in allowed:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (field_name, sorted(allowed)),
        )


def parse_pagination():
    """Parse and validate limit/offset query params (PRD §2.3).

    Raises ERR_INVALID_PAGINATION on out-of-range or non-integer values.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err(
                "ERR_INVALID_PAGINATION",
                "limit must be within [1,100].",
            )

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_PAGINATION", "offset must be >= 0.")

    return limit, offset


def paginate(items):
    """Sort by created_at asc (with _seq tie-break), apply limit/offset, and
    build the pagination meta block. Returns (page_items, pagination_meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination
