"""Standard response envelope (PRD §2.2). Fixed field names: meta / response_type / data."""
import random
import string

from flask import jsonify

from clock import clock

# Internal bookkeeping fields that must never appear in serialized output.
_PRIVATE = {"_seq", "_posted_ded_applied", "_posted_patient_resp"}


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphanum) for _ in range(20))


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in _PRIVATE}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data) if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, has_more, status=200):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": _clean(items),
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
