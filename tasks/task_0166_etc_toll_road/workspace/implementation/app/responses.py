"""Response envelope helpers.

The success envelope is:

    { "meta": { "api_request_id": "req_xxx",
                 "api_request_timestamp": "ISO8601",
                 [pagination fields when listing] },
      "response_type": "object" | "array",
      "data": ... }

The error envelope is:

    { "meta": { "api_request_id": "req_xxx",
                 "api_request_timestamp": "ISO8601" },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." } }
"""
import secrets
import string
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import jsonify

from .clock import iso_now


_ALPHABET = string.ascii_uppercase + string.digits


def _request_id() -> str:
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"req_{suffix}"


def _meta(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_array(items: List[Any], limit: int, offset: int, total_count: int, status: int = 200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def empty(status: int = 204):
    """Return an empty body for 204 responses (no envelope per HTTP semantics)."""
    return ("", status)


def error_envelope(error_id: str, message: str) -> Dict[str, Any]:
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

def parse_pagination(args) -> Tuple[int, int]:
    """Parse limit/offset query params, applying defaults and bounds.

    Defaults from the scaffold: limit=10 (min=1, max=100), offset=0.
    """
    from .errors import ApiError  # local import to break circular dep
    try:
        limit_raw = args.get("limit", default=None)
        offset_raw = args.get("offset", default=None)
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError) as exc:
        raise ApiError("ERR_VALIDATION", 422, f"Invalid pagination parameter: {exc}")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 422, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 422, "offset must be >= 0")
    return limit, offset


def paginate(items: Iterable[Any], limit: int, offset: int) -> Tuple[List[Any], int]:
    items = list(items)
    total = len(items)
    return items[offset : offset + limit], total
