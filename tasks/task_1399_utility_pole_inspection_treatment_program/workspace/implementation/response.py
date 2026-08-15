import uuid
from flask import jsonify

import db
from calc import iso


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso(db.clock_now()),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


def err(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
