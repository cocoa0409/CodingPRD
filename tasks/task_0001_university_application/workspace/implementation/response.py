"""Response envelope helpers.

The envelope structure is defined by SCAFFOLD.yaml's response_envelope section
and PRD §2.2. Success responses use response_type "object" or "array" and place
the resource under "data". Error responses use response_type "error" and place
{error_id, message} under "data".
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _format_iso_now() -> str:
    """ISO 8601 UTC instant with three fractional digits, terminated by 'Z'."""
    now = datetime.now(timezone.utc)
    # Truncate microseconds to milliseconds (three fractional digits)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def _new_request_id() -> str:
    suffix = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=20)
    )
    return f"req_{suffix}"


def _base_meta():
    return {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _format_iso_now(),
    }


def success_object(data, http_status: int = 200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_array(data_list, *, limit: int, offset: int, total_count: int,
                  http_status: int = 200):
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
    return jsonify(body), http_status


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
