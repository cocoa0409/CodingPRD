"""Response envelope helpers (PRD 2.2).

Success:  {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:    {"meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...}}
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _now_stamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_meta():
    return {"api_request_id": request_id(),
            "api_request_timestamp": _now_stamp()}


def ok(data=None, status=200):
    body = {"meta": base_meta(),
            "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    """List envelope: the four pagination fields live inside meta, and only
    list endpoints carry them."""
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {"meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status
