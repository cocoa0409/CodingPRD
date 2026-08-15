import uuid

from flask import jsonify

from db import CLOCK, fmt_ts


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(CLOCK.now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination(args):
    """limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, args, serialize):
    """Sort by (created_at ASC, seq ASC), then apply limit/offset."""
    limit, offset = parse_pagination(args)
    rows = sorted(rows, key=lambda r: (r["created_at"], r.get("seq") if r.get("seq") is not None else r.get("rekey_seq", 0)))
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serialize(r) for r in page], total, limit, offset)
