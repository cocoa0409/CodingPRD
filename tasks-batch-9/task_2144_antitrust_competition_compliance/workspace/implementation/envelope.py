"""Standard response envelope (PRD 2.2)."""
from flask import jsonify

from store import new_request_id, now_wall, iso_ms


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_ms(now_wall()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def array_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), code
