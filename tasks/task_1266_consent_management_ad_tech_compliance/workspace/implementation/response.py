"""Response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope).

Success object:
    { "meta": {api_request_id, api_request_timestamp},
      "response_type": "object", "data": {...} }

Success list:
    same, but response_type "array", data [...], and meta additionally carries
    limit / offset / total_count / has_more.

Error:
    { "meta": {api_request_id, api_request_timestamp},
      "response_type": "error",
      "data": {"error_id": ..., "message": ...} }

meta.api_request_timestamp is the REAL wall-clock UTC now (3 fractional
digits) — unlike entity timestamps, which come from the logical clock.
"""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError, ERR_INVALID_REQUEST

_ALPHANUM = string.ascii_letters + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def ok(data, status=200):
    """Single-resource success envelope."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    """List success envelope with pagination fields in meta."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, message, http_status):
    """Error envelope (meta carries only request id + timestamp)."""
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params: default 10/0, clamp to [1,100]/[0,inf)."""
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    try:
        limit = DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
        offset = DEFAULT_OFFSET if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError(
            ERR_INVALID_REQUEST, "limit and offset must be integers", 400
        )
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    offset = max(DEFAULT_OFFSET, offset)
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (stable: insertion order breaks ties) and slice.

    `id` is identity only and is never used for ordering or tie-breaking.
    """
    ordered = sorted(items, key=lambda e: e.get("created_at", ""))
    total = len(ordered)
    return ordered[offset : offset + limit], total
