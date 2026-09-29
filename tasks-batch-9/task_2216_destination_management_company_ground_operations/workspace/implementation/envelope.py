"""Response envelope helpers (PRD section 2.2)."""

import random
import string

from flask import jsonify

from store import fmt_dt, utcnow

_ALPHANUM = string.ascii_uppercase + string.digits


def _meta():
    suffix = "".join(random.choice(_ALPHANUM) for _ in range(20))
    return {
        "api_request_id": "req_" + suffix,
        "api_request_timestamp": fmt_dt(utcnow()),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
