"""Response envelope helpers (PRD §2.2, §2.3; SCAFFOLD §1.0).

Success:  { "meta": {...}, "response_type": "object"|"array", "data": ... }
Error:    { "meta": {...}, "response_type": "error",
            "data": { "error_id": ..., "message": ... } }
List responses add limit/offset/total_count/has_more to meta.
"""

from flask import jsonify, request

from db import iso, new_request_id, now, public


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(now()),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_obj(ent, code=200):
    return ok(public(ent), code)


def _page_params():
    """limit: default 10, min 1, max 100; offset: default 0 (PRD §2.3)."""
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    return limit, offset


def ok_list(items):
    """items: full filtered entity list; sorted by created_at ascending
    (insertion seq breaks ties), then paginated."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    limit, offset = _page_params()
    total = len(ordered)
    page = [public(e) for e in ordered[offset:offset + limit]]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def err_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
