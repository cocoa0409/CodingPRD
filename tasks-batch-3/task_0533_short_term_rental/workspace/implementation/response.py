"""Standard response envelope helpers."""
from flask import jsonify

from clock import format_iso_ms
from db import new_request_id
from clock import Clock


def _meta(extra=None):
    from datetime import datetime, timezone
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
