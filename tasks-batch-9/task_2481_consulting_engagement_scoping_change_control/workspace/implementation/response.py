"""Response envelope helpers.

Envelope field names come from SCAFFOLD.response_envelope / PRD 2.2:
  success: { "meta": {...}, "response_type": "object"|"array", "data": ... }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": ..., "message": ... } }
Pagination fields inside meta: limit, offset, total_count, has_more.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_now():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _wall_now()}


def ok(data, status=200):
    return jsonify({"meta": base_meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
