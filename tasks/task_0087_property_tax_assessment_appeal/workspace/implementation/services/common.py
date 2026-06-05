"""Shared helpers: body parsing, validation utilities, pagination, lookups."""
from flask import request

import db
from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_body():
    """Return the JSON body as a dict (empty dict when no body)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def parse_pagination():
    """Read limit/offset query params with defaults/bounds (PRD §2.3).

    limit default 10, min 1, max 100; offset default 0.
    """
    args = request.args

    raw_limit = args.get("limit")
    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST", "limit out of range")

    raw_offset = args.get("offset")
    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (PRD §2.3) then apply the window."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


def lookup(collection, resource_id):
    """Fetch a stored resource or raise ERR_NOT_FOUND (PRD §2.6)."""
    rec = collection.get(resource_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist")
    return rec


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def recompute_outstanding(agreement):
    agreement["outstanding_balance_cents"] = (
        agreement["deferred_principal_cents"]
        + agreement["accrued_interest_cents"]
        - agreement["total_paid_cents"]
    )
