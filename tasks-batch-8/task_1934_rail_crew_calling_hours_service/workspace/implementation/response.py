"""Standard response envelope helpers (PRD §2.2 / §2.3)."""
from flask import jsonify

from db import store, fmt_dt, new_request_id, serialize


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(store.now),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_obj(record, status=200):
    return ok(serialize(record), status)


def ok_list(records, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(records)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in records],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit: default 10, min 1, max 100; offset: default 0 (clamped)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paged(rows, args):
    """Sort by (created_at, insertion seq) ascending, then paginate."""
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination(args)
    total = len(rows)
    return ok_list(rows[offset:offset + limit], total, limit, offset)
