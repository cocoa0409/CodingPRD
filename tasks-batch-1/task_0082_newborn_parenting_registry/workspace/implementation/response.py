"""Standard response envelope helpers (PRD §2.2).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": ISO8601,
              [list-only: "limit","offset","total_count","has_more"] },
    "response_type": "object" | "array", "data": ... }

Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Optional

from flask import jsonify


def _new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _now_iso() -> str:
    # ISO 8601 UTC, three fractional digits, trailing Z (PRD §2.2/§2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extras: Optional[dict] = None) -> dict:
    m = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if extras:
        m.update(extras)
    return m


def ok_object(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_array(items: list, *, limit: int, offset: int, total_count: int,
             has_more: bool, status: int = 200):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def err(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
