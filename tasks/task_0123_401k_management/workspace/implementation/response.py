"""Response envelope builders per PRD §2.2 / §2.3."""

import secrets
import string
from datetime import datetime, timezone
from flask import jsonify

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)


_REQ_ID_ALPHABET = string.ascii_letters + string.digits


def _request_id() -> str:
    suffix = "".join(secrets.choice(_REQ_ID_ALPHABET) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status_code: int = 200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status_code


def success_list(items, total_count: int, limit: int, offset: int):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id: str, message: str, status_code: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status_code


def parse_pagination(args):
    """Extract limit/offset from the request args; clamp to bounds."""
    try:
        limit = int(args.get("limit", PAGINATION_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = PAGINATION_DEFAULT_LIMIT
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(PAGINATION_MIN_LIMIT, min(limit, PAGINATION_MAX_LIMIT))
    offset = max(0, offset)
    return limit, offset
