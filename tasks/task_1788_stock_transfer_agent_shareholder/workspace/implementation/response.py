"""Standard response envelope helpers (PRD section 2.2)."""
from flask import jsonify

from helpers import new_req_id, wallclock_iso


def _meta():
    return {
        "api_request_id": new_req_id(),
        "api_request_timestamp": wallclock_iso(),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    page_count = len(items)
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + page_count) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
