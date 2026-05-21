"""Response envelope helpers — match PRD §2.2 exactly.

Success:
    { "meta": { "api_request_id": "req_xxx",
                "api_request_timestamp": "ISO8601",
                [pagination fields if list] },
      "response_type": "object" | "array",
      "data": {} }

Error:
    { "meta": { "api_request_id": "req_xxx",
                "api_request_timestamp": "ISO8601" },
      "response_type": "error",
      "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any


_ALPHANUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _new_request_id() -> str:
    suffix = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    dt = datetime.now(tz=timezone.utc)
    ms = int(dt.microsecond / 1000)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ms:03d}Z"


def _base_meta() -> dict[str, Any]:
    return {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def object_envelope(data: Any) -> dict[str, Any]:
    return {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }


def array_envelope(
    items: list[Any],
    *,
    limit: int,
    offset: int,
    total_count: int,
) -> dict[str, Any]:
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }


def error_envelope(error_id: str, message: str) -> dict[str, Any]:
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
