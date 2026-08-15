"""Standard response envelope helpers (scaffold §1.0, PRD §2.2/§2.3)."""
from flask import jsonify

from util import iso, now, new_request_id


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(now()),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
