"""Response envelope helpers."""

import secrets
import string
from flask import g, jsonify

from clock import now, format_ts


def gen_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def request_meta():
    rid = getattr(g, "api_request_id", None) or gen_request_id()
    g.api_request_id = rid
    ts = getattr(g, "api_request_timestamp", None)
    if ts is None:
        ts = format_ts(now())
        g.api_request_timestamp = ts
    return {"api_request_id": rid, "api_request_timestamp": ts}


def success_object(data, status=200):
    body = {
        "meta": request_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(items, total, limit, offset, status=200):
    meta = request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def empty_204():
    """For DELETE endpoints — empty body, status 204."""
    from flask import make_response
    resp = make_response("", 204)
    return resp
