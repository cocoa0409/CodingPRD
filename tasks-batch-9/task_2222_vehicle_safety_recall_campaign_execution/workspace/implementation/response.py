"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify, request

from db import fmt_instant, now_wall
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def build_meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(now_wall()),
    }
    if extra:
        meta.update(extra)
    return meta


def single(data, status=200):
    body = {"meta": build_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        if not re_int(raw_limit):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        if not re_int(raw_offset):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        offset = int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
    return limit, offset


def re_int(value):
    value = value.strip()
    if value.startswith("-"):
        return value[1:].isdigit()
    return value.isdigit()


def collection(items, serializer):
    """Paginate an already-ordered list of records and emit the array envelope."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = build_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(item) for item in page],
    }
    return jsonify(body), 200
