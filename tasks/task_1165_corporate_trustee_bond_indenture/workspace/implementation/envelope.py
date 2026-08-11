"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string
from flask import jsonify, request

from errors import ApiError, raise_err, ERR_INVALID_REQUEST
from store import now_iso


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": now_iso()}


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_body():
    """Parse the JSON request body. Empty body -> {}. Malformed JSON -> 400."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        data = request.get_json(force=False, silent=False, cache=True)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0), PRD 2.3."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(rows, filters):
    """Filter (exact match), sort by created_at ascending (stable), paginate."""
    items = list(rows)
    for key, val in filters.items():
        if val is not None:
            items = [e for e in items if str(e.get(key)) == val]
    items = sorted(items, key=lambda e: e.get("created_at", ""))
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return ok_list([public(e) for e in page], limit, offset, total)


def public(e):
    """Strip internal bookkeeping fields (prefixed with '_')."""
    return {k: v for k, v in e.items() if not k.startswith("_")}
