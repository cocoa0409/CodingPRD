"""Standard response envelope helpers (PRD 2.2, SCAFFOLD §1.0).

Success:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601", ...pagination },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def _request_timestamp():
    # ISO 8601 UTC with three fractional digits. This is the server's stamp on
    # the response (wall-clock based, distinct from the logical clock used for
    # business determinations).
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def success(data, status=200, pagination=None):
    meta = _base_meta()
    response_type = "array" if isinstance(data, list) else "object"
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_body(error_id, message):
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
