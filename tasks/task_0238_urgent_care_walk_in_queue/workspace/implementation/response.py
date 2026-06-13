"""Standard response envelope (PRD §2.2 / §1.0)."""
from flask import jsonify
from util import request_id, iso_format
import clock


def _meta(extra=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_format(clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
