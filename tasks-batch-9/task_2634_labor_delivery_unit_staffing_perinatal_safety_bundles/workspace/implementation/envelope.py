"""Response envelope helpers (PRD 2.2) and pagination meta (PRD 2.3)."""

import datetime as _dt
import random
import string

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    stamp = _dt.datetime.now(_dt.timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (stamp.microsecond // 1000)) + "Z"


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return obj(data, 201)


def arr(items, limit, offset, total, has_more, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = has_more
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def obj_paged(data, limit, offset, total, has_more, status=200):
    """A computed read whose embedded row array is paginated (PRD 2.3)."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = has_more
    body = {"meta": meta, "response_type": "object", "data": data}
    return jsonify(body), status
