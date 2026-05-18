"""Response envelope builders.

Implements the exact envelope structure defined in PRD §2.2 and
SCAFFOLD.response_envelope:

success:
  { "meta": { api_request_id, api_request_timestamp [, limit, offset, total_count, has_more] },
    "response_type": "object" | "array",
    "data": {} | [] }

error:
  { "meta": { api_request_id, api_request_timestamp },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""

from datetime import datetime, timezone
from flask import jsonify

from utils import iso_now, new_request_id


def _meta_base() -> dict:
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(datetime.now(tz=timezone.utc)),
    }


def success(data, *, status: int = 200, pagination: dict | None = None):
    """Build a success response.

    `data` is either a dict (response_type=object) or a list (response_type=array).
    For list responses, supply `pagination` (a dict with limit/offset/total_count/has_more)
    so the meta block carries pagination fields.
    """
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
        response_type = "array"
    else:
        response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    response = jsonify(body)
    response.status_code = status
    return response


def error(error_id: str, message: str, http_status: int):
    """Build an error response envelope."""
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    response = jsonify(body)
    response.status_code = http_status
    return response
