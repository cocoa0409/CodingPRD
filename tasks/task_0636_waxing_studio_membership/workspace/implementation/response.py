"""Response envelope helpers (PRD 2.2)."""
from flask import jsonify

from util import new_request_id, iso
from clock import clock


def _meta(extra=None):
    # api_request_timestamp is a server-generated ISO8601 UTC timestamp with
    # three fractional digits. It tracks the logical clock so deterministic
    # tests see a stable timestamp.
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(clock.get()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
