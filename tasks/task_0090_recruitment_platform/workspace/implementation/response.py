"""Response envelope helpers."""
from __future__ import annotations

import secrets
import string
from typing import Any, Dict, Optional, Tuple

from clock import iso_now


_ALPHABET = string.ascii_letters + string.digits


def _request_id() -> str:
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"req_{suffix}"


def _meta(pagination: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    m: Dict[str, Any] = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }
    if pagination:
        m.update(pagination)
    return m


def success_object(data: Any, http_status: int = 200) -> Tuple[Dict[str, Any], int]:
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return body, http_status


def success_array(
    data: list,
    *,
    limit: int,
    offset: int,
    total_count: int,
    http_status: int = 200,
) -> Tuple[Dict[str, Any], int]:
    has_more = (offset + len(data)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": data,
    }
    return body, http_status


def empty_success(http_status: int = 200) -> Tuple[Dict[str, Any], int]:
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {},
    }
    return body, http_status


def error_response(error_id: str, message: str, http_status: int) -> Tuple[Dict[str, Any], int]:
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body, http_status
