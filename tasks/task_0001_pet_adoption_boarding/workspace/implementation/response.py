"""Response envelope helpers.

Envelope format:
  success (object):  { meta: {api_request_id, api_request_timestamp}, response_type: "object", data: {} }
  success (array):   { meta: {..., limit, offset, total_count, has_more}, response_type: "array", data: [] }
  error:             { meta: {...}, response_type: "error", data: {error_id, message} }

Timestamps: ISO 8601 UTC with exactly three fractional-second digits.
"""

import uuid
from datetime import datetime, timezone
from flask import jsonify


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:16]


def _base_meta() -> dict:
    return {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success_object(data, status_code: int = 200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def success_array(data_list, limit: int, offset: int, total_count: int, status_code: int = 200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(data_list)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data_list,
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def error_response(error_id: str, message: str, status_code: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp
