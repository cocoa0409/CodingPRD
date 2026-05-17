"""Response envelope helpers.

Every successful response is wrapped in:
    {
      "meta": { api_request_id, api_request_timestamp, (limit/offset/...) },
      "response_type": "object" | "array",
      "data": ...
    }

Error responses:
    {
      "meta": { api_request_id, api_request_timestamp },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." }
    }
"""
from typing import Any, Dict, List, Optional

from app.store import store


def _meta() -> Dict[str, Any]:
    return {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def success_object(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }


def success_array(
    data: List[Dict[str, Any]],
    limit: int,
    offset: int,
    total_count: int,
) -> Dict[str, Any]:
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(data)) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": data,
    }


def error_envelope(error_id: str, message: str) -> Dict[str, Any]:
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
