"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _stamp():
    # The envelope timestamp is the real server clock, not the logical clock.
    now = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second,
        now.microsecond // 1000,
    )


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": _stamp()}


def obj(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def created(data):
    return obj(data, 201)


def collection(items, limit, offset, total_count):
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
