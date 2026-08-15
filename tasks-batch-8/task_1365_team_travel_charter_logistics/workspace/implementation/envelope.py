"""Standard response envelope helpers per PRD §2.2."""
import random
import string

from flask import jsonify

from state import now_iso


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200):
    """Single-resource (object) success envelope."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    """List success envelope with pagination fields in meta."""
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
