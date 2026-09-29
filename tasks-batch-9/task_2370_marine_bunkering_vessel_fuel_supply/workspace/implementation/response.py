"""Standard response envelope (PRD 2.2)."""

import random
import string

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(db.now()),
    }


def success(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
