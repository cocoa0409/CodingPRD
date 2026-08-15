"""Response envelope helpers — exact structure from the scaffold's
response_envelope table (meta / response_type / data; pagination fields
limit, offset, total_count, has_more inside meta for list responses)."""
import random
import string

from flask import jsonify, request

from db import wall_ts
from errors import ApiError


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": wall_ts()}


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items):
    limit, offset = _pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def _pagination_params():
    limit = _parse_qp("limit", 10)
    offset = _parse_qp("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_qp(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status
