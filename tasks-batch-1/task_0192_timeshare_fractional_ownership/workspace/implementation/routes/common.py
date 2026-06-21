"""Shared route helpers: pagination, listing, FK resolution, ownership."""
from flask import request

import errors
from db import db
from response import success

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def parse_pagination():
    """Parse limit/offset from query params per PRD 2.3.

    limit default 10, min 1, max 100; offset default 0.
    Invalid values -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.err(
                errors.ERR_INVALID_REQUEST,
                "limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
            )

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0.")

    return limit, offset


def list_response(items, serializer):
    """Sort by created_at ASC (stable via _seq), paginate, and emit array envelope."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda o: o["_seq"])
    total = len(ordered)
    page = ordered[offset : offset + limit]
    data = [serializer(o) for o in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success(data, status=200, pagination=pagination)


def get_or_404(collection, resource_id):
    obj = collection.get(resource_id)
    if obj is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found: %s" % resource_id)
    return obj


def get_json():
    """Return request JSON body or {} when absent; raise ERR_INVALID_REQUEST on malformed JSON."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Ownership check (priority 3): Owner X-User-ID must equal the owner_id of the
# contract the resource belongs to.
# ---------------------------------------------------------------------------
def check_owner_of_contract(role, user_id, contract):
    if role == "Owner" and contract["owner_id"] != user_id:
        raise errors.err(
            errors.ERR_NOT_RESOURCE_OWNER,
            "Owner does not own the contract this resource belongs to.",
        )
