"""Standard envelope serializer from PRD §2.2.

Every successful response is `{meta, response_type, data}` and every error
is `{meta, response_type: "error", data: {error_id, message}}`.
"""
from __future__ import annotations

import datetime as _dt
import random
import string
import uuid
from typing import Any, Dict, Optional, Tuple

from flask import Response, g, jsonify, make_response


def _alnum(length: int) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=length))


def new_request_id() -> str:
    """Generate a fresh request id of the form `req_<20 alnum>`."""
    return f"req_{_alnum(20)}"


def server_now_iso8601() -> str:
    """The server's wall-clock time formatted as ISO 8601 UTC with millis.

    The PRD pins three fractional digits.  Python's datetime.isoformat()
    produces microseconds; we truncate to milliseconds and append `Z`.
    """
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    # Build manually so the precision is always exactly three fractional digits.
    millis = int(now.microsecond / 1000)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def epoch_to_iso8601(epoch_seconds: float | int) -> str:
    """Convert a Unix-seconds float/int into the canonical ISO 8601 UTC string."""
    dt = _dt.datetime.fromtimestamp(float(epoch_seconds), tz=_dt.timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def fresh_uuid() -> str:
    """A bare hex-dash UUID, no entity-type prefix, per PRD §2.4."""
    return str(uuid.uuid4())


def _meta_base() -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "api_request_id": getattr(g, "api_request_id", new_request_id()),
        "api_request_timestamp": getattr(
            g, "api_request_timestamp", server_now_iso8601()
        ),
    }
    if getattr(g, "is_idempotent_replay", False):
        meta["is_idempotent_replay"] = True
    return meta


def success_envelope(
    data: Any,
    http_status: int = 200,
    *,
    pagination: Optional[Dict[str, Any]] = None,
    response_type: Optional[str] = None,
) -> Response:
    """Wrap `data` in the standard success envelope.

    `pagination` carries the four fields ``limit``, ``offset``,
    ``total_count``, ``has_more`` for list responses.
    The ``response_type`` defaults to ``"array"`` when `data` is a list,
    else ``"object"`` — the PRD pins this exact discriminator.
    """
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = make_response(jsonify(body), http_status)
    resp.headers["Content-Type"] = "application/json"
    return resp


def error_envelope_response(error_id: str, message: str, http_status: int) -> Response:
    """Build the standard error envelope per PRD §2.2.

    The error envelope's `meta` carries only `api_request_id` and
    `api_request_timestamp` per PRD prose, and the `data` carries the
    two-field `{error_id, message}` payload.
    """
    body = {
        "meta": {
            "api_request_id": getattr(g, "api_request_id", new_request_id()),
            "api_request_timestamp": getattr(
                g, "api_request_timestamp", server_now_iso8601()
            ),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    resp = make_response(jsonify(body), http_status)
    resp.headers["Content-Type"] = "application/json"
    return resp


def paginate_list(rows: list, query) -> Tuple[list, Dict[str, Any]]:
    """Apply the limit/offset window from PRD §2.3 over an already-sorted list.

    Raises `ApiError("ERR_INVALID_PAGINATION")` on out-of-range values.
    Defaults are limit=10, offset=0, range [1,100] for limit, ≥0 for offset.
    """
    from .errors import ApiError

    raw_limit = query.get("limit")
    raw_offset = query.get("offset")

    def _parse_int(raw: Optional[str], default: int, name: str) -> int:
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ApiError(
                "ERR_INVALID_PAGINATION", f"{name} must be an integer"
            ) from None
        return value

    limit = _parse_int(raw_limit, 10, "limit")
    offset = _parse_int(raw_offset, 0, "offset")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION", "limit out of range [1,100]")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be non-negative")

    total_count = len(rows)
    window = rows[offset : offset + limit]
    has_more = (offset + limit) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return window, pagination
