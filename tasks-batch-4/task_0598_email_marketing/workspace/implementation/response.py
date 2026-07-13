"""Standard response envelope (PRD 2.2, 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

ALNUM = string.ascii_uppercase + string.digits


def _meta():
    rid = "req_" + "".join(random.choice(ALNUM) for _ in range(20))
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (ts.microsecond // 1000)
    return {"api_request_id": rid, "api_request_timestamp": stamp}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
