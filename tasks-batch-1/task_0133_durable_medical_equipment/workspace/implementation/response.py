"""Response envelope helpers (SCAFFOLD Table 1.0 / PRD 2.2).

Success envelope:
    { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": ISO8601,
                [limit, offset, total_count, has_more for lists] },
      "response_type": "object" | "array",
      "data": {} | [] }

Error envelope:
    { "meta": { api_request_id, api_request_timestamp },
      "response_type": "error",
      "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _timestamp():
    # ISO 8601 UTC with exactly three fractional digits, trailing Z.
    dt = clock.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(data, limit, offset, total_count, has_more, status=200):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": data}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
