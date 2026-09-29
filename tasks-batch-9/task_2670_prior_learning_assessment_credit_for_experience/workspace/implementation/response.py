"""Response envelope helpers (PRD 2.2) and offset pagination (PRD 2.3)."""
from flask import jsonify, request

from errors import ApiError
from util import fmt_dt, new_request_id, real_now

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(real_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def no_content():
    return "", 204


def ok_list(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    items = [serializer(r) for r in window]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error", "data": {"error_id": error_id, "message": message}}


def read_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset
