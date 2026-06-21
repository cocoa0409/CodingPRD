"""Standard response envelope helpers (PRD §2.2, scaffold response_envelope).

Success envelope:
    { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
                [pagination fields for lists] },
      "response_type": "object" | "array",
      "data": {} | [] }

Error envelope:
    { "meta": { "api_request_id", "api_request_timestamp" },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_letters + string.digits


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type=None, pagination=None):
    """Wrap `data` in the success envelope.

    response_type defaults to "array" when data is a list, else "object".
    """
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message):
    """Wrap an error in the error envelope."""
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
