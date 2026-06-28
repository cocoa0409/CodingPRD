"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }

api_request_timestamp is server-generated wall-clock ISO 8601 UTC with three
fractional digits (PRD §2.2). This is metadata about the HTTP request, not a
business decision, so it does NOT use the logical clock.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_letters + string.digits

# Fields that are part of the entity model but are internal bookkeeping and must
# not appear in API output.
_PRIVATE_FIELDS = ("_seq",)


def _request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        m.update(extra)
    return m


def _public(entity):
    if not isinstance(entity, dict):
        return entity
    return {k: v for k, v in entity.items() if k not in _PRIVATE_FIELDS}


def success(data, status=200, pagination=None):
    is_array = isinstance(data, list)
    if is_array:
        payload = [_public(e) for e in data]
        response_type = "array"
    else:
        payload = _public(data) if data is not None else {}
        response_type = "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": payload,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
