"""Response envelope helpers — exact field names per PRD §2.2 and scaffold response_envelope."""

import secrets
import string

from flask import jsonify

from clock import now_iso


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _meta_base() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success_object(data, status: int = 200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(data, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + limit) < total_count
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    body = {
        "meta": meta,
        "response_type": "array",
        "data": list(data),
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def parse_pagination(args):
    """Read pagination from query args using scaffold default 10/min1/max100/offset0."""
    from errors import invalid_request
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset
