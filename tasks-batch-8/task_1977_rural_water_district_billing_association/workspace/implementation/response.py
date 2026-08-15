"""Standard response envelope helpers (PRD §2.2 / §2.3)."""
import uuid

from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.now_iso(),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body)


def err(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def parse_pagination(args):
    """limit: default 10, min 1, max 100; offset: default 0. Lenient parsing."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


def paginate(records, args):
    """Sort by (created_at, insertion seq) ascending and slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    limit, offset = parse_pagination(args)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
