"""Response envelope helpers per PRD §2.2/§2.3."""

import secrets
import string

from flask import jsonify, request

import clock
from errors import raise_err


def _request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": clock.now_iso()}


def success(data, code=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def paginate(items):
    """Apply limit/offset query params per PRD §2.3. Returns (page, pagination_meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_VALIDATION", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": (offset + len(page)) < total}


def sort_default(items):
    """Default list ordering: created_at ascending (creation sequence breaks ties)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
