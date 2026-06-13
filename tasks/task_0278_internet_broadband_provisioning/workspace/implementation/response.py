"""Standard response envelope helpers (PRD §2.2).

Success:
{ "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
            [pagination fields for list endpoints] },
  "response_type": "object" | "array", "data": {...} }

Error:
{ "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
  "response_type": "error",
  "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _now_iso():
    # The api_request_timestamp is wall-clock server time (the moment the
    # response is generated), independent of the pinned logical clock.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def array_response(data, limit, offset, total_count, has_more, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message if message is not None else error_id,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
