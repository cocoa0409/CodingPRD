"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope)."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

import db
import errors

_REQ_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_REQ_ALPHABET) for _ in range(22))


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.fmt_ts(datetime.now(timezone.utc)),
    }


def success_object(data, status=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination):
    meta = _meta_base()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(items):
    """Apply limit/offset query params per §2.3. Defaults: limit=10, offset=0;
    limit min 1 max 100. Returns (page_items, pagination_meta)."""
    args = request.args
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    # Reject non-integer spellings like "10.5" that int() would reject anyway,
    # and bool-ish leftovers.
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
