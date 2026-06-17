"""Shared route helpers: body parsing, pagination, list assembly."""
from flask import request

import db
import errors
import response
import middleware as mw


def require_int(body, field, required=True, minimum=None, allow_none=False):
    """Extract an integer field from the body with field-shape validation.

    Raises ERR_INVALID_REQUEST (priority 17) on missing/wrong-type/below-minimum.
    Booleans are rejected (JSON true/false are not integers here).
    """
    val = body.get(field, None)
    if val is None:
        if allow_none:
            return None
        if required:
            raise errors.invalid_request("%s is required." % field)
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("%s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("%s must be >= %d." % (field, minimum))
    return val


def require_account(account_id):
    """Existence check for a referenced account (priority 4)."""
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    return acct


def get_json_body():
    """Return the request JSON body as a dict, or {} for an empty body.

    Malformed JSON -> ERR_INVALID_REQUEST (field-shape validation).
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit: default 10, min 1, max 100.
    offset: default 0, min 0.
    """
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate_list(items, serializer):
    """Sort by created_at asc (PRD §2.3), paginate, and build the list envelope."""
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    data = [serializer(x) for x in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return response.success(data, status=200, is_list=True, pagination=pagination)
