"""Response envelope of PRD section 2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _wall_now():
    value = datetime.now(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def meta_base():
    return {"api_request_id": _request_id(), "api_request_timestamp": _wall_now()}


def ok(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def ok_list(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def err(error_id, message, status):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
