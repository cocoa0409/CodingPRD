"""Standard response envelope helpers (PRD 2.2)."""
import secrets
import string

from flask import jsonify

from db import clock_now, fmt_ts

_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(clock_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, total_count, limit, offset):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err_response(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status
