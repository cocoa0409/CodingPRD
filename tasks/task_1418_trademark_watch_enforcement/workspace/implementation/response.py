"""Standard response envelope helpers per PRD sections 2.2 and 2.3."""

import random
import string

from flask import jsonify

import db
from db import _format_iso


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _format_iso(db.clock.now()),
    }


def success(data, status=200, pagination=None):
    """Build the success envelope; pagination adds limit/offset/total_count/has_more."""
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def parse_pagination(args):
    """limit: default 10, min 1, max 100; offset: default 0, min 0 (PRD 2.3)."""
    from errors import raise_error, ERR_VALIDATION

    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate_list(items, limit, offset):
    """Every list endpoint returns resources sorted by created_at ascending."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
