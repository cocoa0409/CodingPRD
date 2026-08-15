"""Response envelope helpers (PRD §2.2, §2.3).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "..." },
    "response_type": "object" | "array", "data": ... }
  List responses add limit/offset/total_count/has_more to meta.

Error envelope:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""

import random
import string
from flask import jsonify

from timeutil import iso_ts_ms


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ts_ms(),
    }


def success_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_resp(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
