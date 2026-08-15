"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD §1.0)."""
import secrets
import string

from flask import request

from db import now_iso
from errors import ApiError, invalid_request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, http_status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return body, http_status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, 200


def ok_report(data, limit, offset, total_count):
    """Computed report object that also carries pagination meta."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return {"meta": meta, "response_type": "object", "data": data}, 200


def error_body(err: ApiError):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }, err.http_status


def pagination_params():
    """Parse limit/offset query params with clamping (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < MIN_LIMIT:
            limit = MIN_LIMIT
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows):
    """rows: full filtered+sorted list of serialized dicts."""
    limit, offset = pagination_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list(window, limit, offset, total)
