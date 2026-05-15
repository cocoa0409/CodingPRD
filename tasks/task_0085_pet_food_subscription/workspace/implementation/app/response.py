"""Standard response envelope helpers (PRD §2.2)."""
from __future__ import annotations

import secrets
import string
from typing import Any, Dict, Optional, Tuple

from flask import jsonify

from app.utils import now_iso


_ALPHABET = string.ascii_uppercase + string.digits


def make_request_id() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"req_{body}"


def _meta(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "api_request_id": make_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data: Any, status: int = 200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def success_array(data, limit: int, offset: int, total_count: int, status: int = 200):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": list(data)}
    return jsonify(body), status


def success_empty(status: int = 200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def error_envelope(error_id: str, message: str, http_status: int) -> Tuple[Dict[str, Any], int]:
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, http_status
