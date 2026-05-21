"""Response envelope helpers (PRD §2.2)."""

from typing import Any, Dict, Optional

from flask import g, jsonify

from db import new_request_id, utcnow_iso


def _meta() -> Dict[str, Any]:
    """Per-request metadata: api_request_id + api_request_timestamp."""
    req_id = getattr(g, "api_request_id", None) or new_request_id()
    return {
        "api_request_id": req_id,
        "api_request_timestamp": utcnow_iso(),
    }


def ok(data: Any, status: int = 200, pagination: Optional[Dict[str, Any]] = None):
    """Success response with `response_type` and `data` payload."""
    meta = _meta()
    is_array = isinstance(data, list)
    if pagination is not None:
        # Pagination fields are surfaced on the meta wrapper for list responses.
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_array else "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def err(error_id: str, message: str, status: int):
    """Error response with `response_type=error` and `error_id`+`message` in data."""
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def paginate(items: list, limit: int, offset: int) -> Dict[str, Any]:
    """Compute pagination metadata and slice the list in one helper.
    Returns the dict to merge into meta. Caller passes the SLICE separately."""
    total = len(items)
    end = offset + limit
    sliced = items[offset:end]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": end < total,
    }
