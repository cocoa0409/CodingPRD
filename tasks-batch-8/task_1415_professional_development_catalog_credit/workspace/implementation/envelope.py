"""Standard response envelope helpers (scaffold response_envelope)."""
import random
import string

from flask import jsonify, request

from db import fmt_ts, wall_now
from errors import ApiError, err, ERR_INVALID_REQUEST


def _meta_base():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": fmt_ts(wall_now())}


def ok(data, code=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total, limit, offset):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(e):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0, min 0. Clamp."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(serialized_items):
    """Items must already be serialized and sorted by created_at asc."""
    limit, offset = pagination_params()
    total = len(serialized_items)
    page = serialized_items[offset:offset + limit]
    return ok_list(page, total, limit, offset)


def get_body():
    """Parsed JSON body; malformed/missing JSON is treated as {} so that
    required-field validation produces ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def sort_by_created(items):
    return sorted(items, key=lambda o: (o["created_at"], o.get("_seq", 0)))
