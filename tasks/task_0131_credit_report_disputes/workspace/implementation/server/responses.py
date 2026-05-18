"""Response envelope helpers.

The response envelope shape comes verbatim from SCAFFOLD.yaml §1.0 and PRD §2.2:

    success: { meta: { api_request_id, api_request_timestamp, [pagination...] },
               response_type: "object" | "array",
               data: {} }
    error  : { meta: { api_request_id, api_request_timestamp },
               response_type: "error",
               data: { error_id, message } }
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any

from flask import jsonify


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _timestamp() -> str:
    """ISO 8601 UTC with millisecond precision and trailing 'Z'."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta() -> dict[str, Any]:
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def json_object(data: Any, status: int = 200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def json_array(
    data: list[Any],
    *,
    limit: int,
    offset: int,
    total_count: int,
    status: int = 200,
):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(data)) < total_count
    body = {"meta": meta, "response_type": "array", "data": data}
    return jsonify(body), status


def json_error(error_id: str, message: str, status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
