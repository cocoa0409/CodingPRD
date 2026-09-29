"""Standard response envelope (PRD 2.2 / 2.3)."""
import random
import string

from flask import jsonify

from db import now, public, sorted_records
from timeutil import fmt_dt

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(data) if isinstance(data, dict) else data,
    }
    return jsonify(body), status


def raw_object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def empty_response(status=200):
    return raw_object_response({}, status)


def list_response(records, limit, offset):
    ordered = sorted_records(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in window],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
