"""Standard response envelope per scaffold §1.0 / PRD §2.2 and §2.3."""
from decimal import Decimal

from flask import jsonify

from util import new_request_id, now_ts


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _jsonable(data),
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": _jsonable(items),
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
